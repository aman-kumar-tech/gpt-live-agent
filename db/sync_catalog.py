"""Non-destructive catalog sync: upserts tests, packages, package_tests,
symptom_routes, and offers from data.json into Postgres.

Unlike db/seed.py, this never truncates anything and never touches
patients/appointments/reports/pending_actions/lab_info -- safe to run
against a database that already has real call activity in it. Use this
after editing data.json's catalog (individual_tests, health_packages,
symptoms_and_conditions_routing, promotions_and_discounts) to pick up the
changes without losing accumulated call data. Use db/seed.py only for a
fresh/throwaway database.

Matching key per table (how "already exists" is decided):
- tests: Test.code
- packages: Package.code
- package_tests: recomputed for every package touched above (old rows for
  that package_id replaced with what data.json currently says)
- symptom_routes: condition_keyword
- offers: title (offers has no natural unique code column in the schema)
"""

import asyncio
import json
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import delete, select

from receptionist.db.engine import dispose_engine, get_session_factory
from receptionist.db.models import Offer, Package, PackageTest, SymptomRoute, Test
from receptionist.winasync import ensure_selector_event_loop

ensure_selector_event_loop()

DATA_PATH = Path(__file__).parent.parent / "data.json"


def _split_codes(codes: list[str]) -> tuple[list[str], list[str]]:
    package_codes = [c for c in codes if c.startswith("PKG_")]
    test_codes = [c for c in codes if not c.startswith("PKG_")]
    return test_codes, package_codes


async def _sync_tests(session, data) -> dict[str, Test]:
    existing = {t.code: t for t in (await session.execute(select(Test))).scalars().all()}
    tests_by_code: dict[str, Test] = {}

    for t in data["individual_tests"]:
        code = t["test_code"]
        fields = dict(
            name=t["canonical_name"],
            aliases=t.get("aliases", []),
            description=t.get("description"),
            category=t.get("category"),
            price=t["standalone_price_inr"],
            sample_type=t.get("sample_type"),
            home_collection_available=t.get("home_collection_eligible", True),
            turnaround_time_hours=t.get("turnaround_time_hours"),
            fasting_required=t.get("fasting_required", False),
            fasting_instructions=t.get("fasting_instructions"),
        )
        if code in existing:
            test = existing[code]
            for key, value in fields.items():
                setattr(test, key, value)
        else:
            test = Test(code=code, **fields)
            session.add(test)
        tests_by_code[code] = test

    await session.flush()
    return tests_by_code


async def _sync_packages(session, data, tests_by_code: dict[str, Test]) -> dict[str, Package]:
    existing = {p.code: p for p in (await session.execute(select(Package))).scalars().all() if p.code}
    packages_by_code: dict[str, Package] = {}

    for p in data["health_packages"]:
        code = p["package_code"]
        fields = dict(
            name=p["package_name"],
            category=p.get("category"),
            value_proposition=p.get("value_proposition"),
            price=p["estimated_package_price_inr"],
            fasting_required=p.get("fasting_required", False),
            fasting_instructions=p.get("fasting_instructions"),
        )
        if code in existing:
            package = existing[code]
            for key, value in fields.items():
                setattr(package, key, value)
        else:
            package = Package(code=code, **fields)
            session.add(package)
        packages_by_code[code] = package

    await session.flush()

    for p in data["health_packages"]:
        package = packages_by_code[p["package_code"]]
        await session.execute(delete(PackageTest).where(PackageTest.package_id == package.id))
        for test_code in p.get("included_test_codes", []):
            test = tests_by_code.get(test_code)
            if test is not None:
                session.add(PackageTest(package_id=package.id, test_id=test.id))

    return packages_by_code


async def _sync_symptom_routes(session, data) -> None:
    existing = {
        r.condition_keyword: r
        for r in (await session.execute(select(SymptomRoute))).scalars().all()
    }
    for route in data.get("symptoms_and_conditions_routing", []):
        test_codes, package_codes = _split_codes(route.get("recommended_tests", []))
        fields = dict(
            symptoms=route.get("symptoms", []),
            recommended_test_codes=test_codes,
            recommended_package_codes=package_codes,
            voice_script_hint=route.get("voice_script_hint"),
        )
        keyword = route["condition_keyword"]
        if keyword in existing:
            for key, value in fields.items():
                setattr(existing[keyword], key, value)
        else:
            session.add(SymptomRoute(condition_keyword=keyword, **fields))


async def _sync_offers(session, data, packages_by_code: dict[str, Package]) -> None:
    existing = {o.title: o for o in (await session.execute(select(Offer))).scalars().all()}
    today = date.today()
    one_year = today + timedelta(days=365)

    for offer in data.get("promotions_and_discounts", []):
        discount_percent = offer.get("discount_percent")
        applies_to_type, applies_to_id = "all", None
        if offer.get("applicable_on") and "package" in offer["applicable_on"].lower():
            for package in packages_by_code.values():
                if package.name.lower() in offer["applicable_on"].lower():
                    applies_to_type, applies_to_id = "package", package.id
                    break

        fields = dict(
            description=offer.get("voice_prompt_trigger"),
            discount_type="percent" if discount_percent is not None else "other",
            discount_value=discount_percent,
            format_note=offer.get("format"),
            eligibility_note=f"{offer.get('eligibility', '')}; applies to {offer.get('applicable_on', '')}".strip("; "),
            applies_to_type=applies_to_type,
            applies_to_id=applies_to_id,
        )
        title = offer["title"]
        if title in existing:
            for key, value in fields.items():
                setattr(existing[title], key, value)
        else:
            session.add(Offer(title=title, start_date=today, end_date=one_year, **fields))


async def main() -> None:
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))

    session_factory = get_session_factory()
    async with session_factory() as session:
        tests_by_code = await _sync_tests(session, data)
        packages_by_code = await _sync_packages(session, data, tests_by_code)
        await _sync_symptom_routes(session, data)
        await _sync_offers(session, data, packages_by_code)
        await session.commit()

    await dispose_engine()
    print(f"Catalog synced from {DATA_PATH.name} (tests, packages, symptom routes, offers) -- "
          f"patients/appointments/reports/pending_actions untouched.")


if __name__ == "__main__":
    asyncio.run(main())
