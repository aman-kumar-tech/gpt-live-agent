"""Loads db/../data.json (the real Dr Lal PathLabs Baner branch export) into
Postgres: lab info, the test/package catalog with aliases and fasting
notes, symptom-to-test routing, and promotions. Patients/reports/appointments
aren't in data.json, so a small set of realistic sample ones is added on top
so the demo is usable immediately.

Safe to re-run: truncates and reloads every table it touches."""

import asyncio
import json
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import text

from receptionist.db.engine import dispose_engine, get_session_factory
from receptionist.db.models import (
    Appointment,
    AppointmentItem,
    LabInfo,
    Offer,
    Package,
    PackageTest,
    Patient,
    Report,
    SymptomRoute,
    Test,
)
from receptionist.winasync import ensure_selector_event_loop

ensure_selector_event_loop()

DATA_PATH = Path(__file__).parent.parent / "data.json"

TABLES = (
    "appointment_items",
    "appointments",
    "reports",
    "package_tests",
    "symptom_routes",
    "offers",
    "packages",
    "tests",
    "patients",
    "lab_info",
    "pending_actions",
)

_WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _parse_time_12h(value: str) -> str:
    return datetime.strptime(value.strip(), "%I:%M %p").strftime("%H:%M")


def _parse_hours_range(range_str: str) -> tuple[str, str]:
    start, end = (p.strip() for p in range_str.split("-"))
    return _parse_time_12h(start), _parse_time_12h(end)


def _build_hours(operating_hours: dict) -> dict:
    """data.json groups days as e.g. "mon_sat"/"sun" -- expand to one entry
    per weekday, matching what get_lab_info/_format_hours expects."""
    hours = {day: {"open": None, "close": None} for day in _WEEKDAYS}
    for group, range_str in operating_hours.items():
        open_, close_ = _parse_hours_range(range_str)
        days = group.split("_") if "_" in group else [group]
        if len(days) == 2:
            start_idx, end_idx = _WEEKDAYS.index(days[0]), _WEEKDAYS.index(days[1])
            days = list(_WEEKDAYS[start_idx : end_idx + 1])
        for day in days:
            hours[day] = {"open": open_, "close": close_}
    return hours


def _split_codes(codes: list[str]) -> tuple[list[str], list[str]]:
    package_codes = [c for c in codes if c.startswith("PKG_")]
    test_codes = [c for c in codes if not c.startswith("PKG_")]
    return test_codes, package_codes


async def main() -> None:
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))

    session_factory = get_session_factory()
    async with session_factory() as session:
        await session.execute(text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE"))

        # --- lab_info -------------------------------------------------
        lab_meta = data["lab_metadata"]
        session.add(
            LabInfo(
                id=1,
                name=lab_meta["name"],
                address=lab_meta["full_address"],
                phone_number=lab_meta["contact_numbers"][0],
                hours=_build_hours(lab_meta["operating_hours"]),
                email=None,
                metadata_={
                    "center_id": lab_meta.get("center_id"),
                    "branch_name": lab_meta.get("branch_name"),
                    "landmark": lab_meta.get("landmark"),
                    "geo_location": lab_meta.get("geo_location"),
                    "contact_numbers": lab_meta.get("contact_numbers"),
                    "accreditations": lab_meta.get("accreditations"),
                    "facilities": lab_meta.get("facilities"),
                    "payment_methods_accepted": lab_meta.get("payment_methods_accepted"),
                },
                operational_rules=data.get("operational_rules", {}),
            )
        )

        # --- tests ------------------------------------------------------
        tests_by_code: dict[str, Test] = {}
        for t in data["individual_tests"]:
            test = Test(
                code=t["test_code"],
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
            session.add(test)
            tests_by_code[t["test_code"]] = test
        await session.flush()

        # --- packages + package_tests ------------------------------------
        packages_by_code: dict[str, Package] = {}
        for p in data["health_packages"]:
            package = Package(
                code=p["package_code"],
                name=p["package_name"],
                category=p.get("category"),
                description=None,
                value_proposition=p.get("value_proposition"),
                price=p["estimated_package_price_inr"],
                fasting_required=p.get("fasting_required", False),
                fasting_instructions=p.get("fasting_instructions"),
            )
            session.add(package)
            packages_by_code[p["package_code"]] = package
        await session.flush()

        for p in data["health_packages"]:
            package = packages_by_code[p["package_code"]]
            for test_code in p.get("included_test_codes", []):
                test = tests_by_code.get(test_code)
                if test is not None:
                    session.add(PackageTest(package_id=package.id, test_id=test.id))

        # --- symptom routing ----------------------------------------------
        for route in data.get("symptoms_and_conditions_routing", []):
            test_codes, package_codes = _split_codes(route.get("recommended_tests", []))
            session.add(
                SymptomRoute(
                    condition_keyword=route["condition_keyword"],
                    symptoms=route.get("symptoms", []),
                    recommended_test_codes=test_codes,
                    recommended_package_codes=package_codes,
                    voice_script_hint=route.get("voice_script_hint"),
                )
            )

        # --- promotions -----------------------------------------------------
        today = date.today()
        one_year = today + timedelta(days=365)
        for offer in data.get("promotions_and_discounts", []):
            discount_percent = offer.get("discount_percent")
            applies_to_type = "all"
            applies_to_id = None
            if offer["applicable_on"] and "package" in offer["applicable_on"].lower():
                # e.g. "SwasthFit Complete Packages" -- best-effort match by name fragment.
                for code, package in packages_by_code.items():
                    if package.name.lower() in offer["applicable_on"].lower():
                        applies_to_type, applies_to_id = "package", package.id
                        break

            session.add(
                Offer(
                    title=offer["title"],
                    description=offer.get("voice_prompt_trigger"),
                    discount_type="percent" if discount_percent is not None else "other",
                    discount_value=discount_percent,
                    format_note=offer.get("format"),
                    eligibility_note=f"{offer.get('eligibility', '')}; applies to {offer.get('applicable_on', '')}".strip("; "),
                    applies_to_type=applies_to_type,
                    applies_to_id=applies_to_id,
                    start_date=today,
                    end_date=one_year,
                )
            )

        # --- sample patients/reports/appointments (not in data.json) ------
        p1 = Patient(first_name="Priya", last_name="Sharma", phone_number="+919812340001", date_of_birth=date(1990, 4, 12), email="priya@example.com")
        p2 = Patient(first_name="Rohan", last_name="Sharma", phone_number="+919812340001", date_of_birth=date(1988, 11, 2))  # shares phone with p1
        p3 = Patient(first_name="Amit", last_name="Verma", phone_number="+919812340002", date_of_birth=date(1975, 2, 20))
        p4 = Patient(first_name="Neha", last_name="Gupta", phone_number="+919812340003", date_of_birth=date(2001, 7, 30))
        p5 = Patient(first_name="Sanjay", last_name="Rao", phone_number="+919812340004", date_of_birth=date(1965, 9, 15))
        session.add_all([p1, p2, p3, p4, p5])
        await session.flush()

        now = datetime.now()
        session.add_all([
            Report(patient_id=p1.id, test_id=tests_by_code["T001"].id, status="ready", sample_collected_at=now - timedelta(days=3), ready_at=now - timedelta(days=2), report_url="https://example-lab.test/reports/demo-1"),
            Report(patient_id=p1.id, test_id=tests_by_code["T006"].id, status="pending"),
            Report(patient_id=p3.id, package_id=packages_by_code["PKG_SUPER4"].id, status="processing", sample_collected_at=now - timedelta(hours=6)),
            Report(patient_id=p4.id, test_id=tests_by_code["T003"].id, status="ready", sample_collected_at=now - timedelta(days=1), ready_at=now - timedelta(hours=10), report_url="https://example-lab.test/reports/demo-2"),
            Report(patient_id=p5.id, test_id=tests_by_code["T005"].id, status="delivered", sample_collected_at=now - timedelta(days=10), ready_at=now - timedelta(days=9), report_url="https://example-lab.test/reports/demo-3"),
        ])

        appt1 = Appointment(
            reference_code="AB12CD",
            patient_id=p3.id,
            type="lab_visit",
            status="booked",
            scheduled_at=now + timedelta(days=2, hours=3),
        )
        appt2 = Appointment(
            reference_code="EF34GH",
            patient_id=p4.id,
            type="home_collection",
            status="booked",
            scheduled_at=now + timedelta(days=1, hours=4),
            address="12 Baner Road, Pune",
            home_collection_fee=0,  # order (T003) is below the waiver threshold but seeded fee-free for simplicity
        )
        session.add_all([appt1, appt2])
        await session.flush()
        session.add_all([
            AppointmentItem(appointment_id=appt1.id, package_id=packages_by_code["PKG_SUPER4"].id),
            AppointmentItem(appointment_id=appt2.id, test_id=tests_by_code["T003"].id),
        ])

        await session.commit()

    await dispose_engine()
    print(f"Seed data loaded from {DATA_PATH.name}.")


if __name__ == "__main__":
    asyncio.run(main())
