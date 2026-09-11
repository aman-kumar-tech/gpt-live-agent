from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from receptionist.db.models import Offer, Package, PackageTest, SymptomRoute, Test


async def find_test(session: AsyncSession, name_or_code: str) -> Test | None:
    """Matches by code, canonical name, or any alias -- callers rarely say a
    test's official name (e.g. "sugar test" for HbA1c)."""
    query = name_or_code.strip().lower()
    result = await session.execute(select(Test).where(Test.active.is_(True)))
    for test in result.scalars().all():
        if test.code.lower() == query or query in test.name.lower():
            return test
        if any(query in alias.lower() or alias.lower() in query for alias in test.aliases):
            return test
    return None


async def find_tests_by_codes(session: AsyncSession, codes: list[str]) -> list[Test]:
    if not codes:
        return []
    result = await session.execute(select(Test).where(Test.code.in_(codes)))
    return list(result.scalars().all())


async def find_package(session: AsyncSession, name: str) -> Package | None:
    query = name.strip().lower()
    result = await session.execute(select(Package).where(Package.active.is_(True)))
    for package in result.scalars().all():
        if query in package.name.lower() or (package.code and package.code.lower() == query):
            return package
    return None


async def find_packages_by_codes(session: AsyncSession, codes: list[str]) -> list[Package]:
    if not codes:
        return []
    result = await session.execute(select(Package).where(Package.code.in_(codes)))
    return list(result.scalars().all())


async def get_package_tests(session: AsyncSession, package_id: int) -> list[Test]:
    result = await session.execute(
        select(Test).join(PackageTest, PackageTest.test_id == Test.id).where(PackageTest.package_id == package_id)
    )
    return list(result.scalars().all())


async def find_symptom_route(session: AsyncSession, symptom: str) -> SymptomRoute | None:
    query = symptom.strip().lower()
    result = await session.execute(select(SymptomRoute))
    for route in result.scalars().all():
        if query in route.condition_keyword.lower() or route.condition_keyword.lower() in query:
            return route
        if any(query in s.lower() or s.lower() in query for s in route.symptoms):
            return route
    return None


async def list_active_offers(session: AsyncSession, on_date: date | None = None) -> list[Offer]:
    on_date = on_date or date.today()
    result = await session.execute(
        select(Offer).where(
            Offer.active.is_(True),
            Offer.start_date <= on_date,
            Offer.end_date >= on_date,
        )
    )
    return list(result.scalars().all())


async def offers_for_test(session: AsyncSession, test_id: int, on_date: date | None = None) -> list[Offer]:
    offers = await list_active_offers(session, on_date)
    return [o for o in offers if o.applies_to_type == "all" or (o.applies_to_type == "test" and o.applies_to_id == test_id)]


async def offers_for_package(session: AsyncSession, package_id: int, on_date: date | None = None) -> list[Offer]:
    offers = await list_active_offers(session, on_date)
    return [
        o for o in offers
        if o.applies_to_type == "all" or (o.applies_to_type == "package" and o.applies_to_id == package_id)
    ]
