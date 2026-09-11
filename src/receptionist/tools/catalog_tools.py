from __future__ import annotations

from livekit.agents import RunContext
from livekit.agents.llm import function_tool

from receptionist.call_state import CallState
from receptionist.config import settings
from receptionist.db.engine import get_session_factory
from receptionist.db.repositories import catalog as catalog_repo


def _format_offer(offer) -> str:
    if offer.discount_type == "percent":
        text = f"{offer.title} ({offer.discount_value:.0f}% off"
    elif offer.discount_type == "flat":
        text = f"{offer.title} ({settings.currency_symbol}{offer.discount_value:.2f} off"
    else:
        text = f"{offer.title} ({offer.format_note or 'special offer'}"
    if offer.eligibility_note:
        text += f", {offer.eligibility_note}"
    return text + ")"


def _offers_suffix(offers) -> str:
    if not offers:
        return ""
    return " Current offer: " + "; ".join(_format_offer(o) for o in offers) + "."


@function_tool
async def get_test_info(context: RunContext[CallState], name_or_code: str) -> str:
    """Look up price, description, turnaround time, fasting requirements,
    and home-collection eligibility for a single test by name or code.

    Args:
        name_or_code: The test's name or code, as the caller said it (e.g. "CBC", "sugar test", "vitamin d").
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        test = await catalog_repo.find_test(session, name_or_code)
        if test is None:
            return f"No test found matching '{name_or_code}'."
        offers = await catalog_repo.offers_for_test(session, test.id)

    home = "available" if test.home_collection_available else "not available"
    turnaround = f"{test.turnaround_time_hours} hours" if test.turnaround_time_hours else "not specified"
    result = (
        f"{test.name}: {settings.currency_symbol}{test.price:.2f}, sample type {test.sample_type}, "
        f"turnaround time {turnaround}, home collection {home}."
    )
    if test.fasting_required and test.fasting_instructions:
        result += f" Fasting: {test.fasting_instructions}"
    return result + _offers_suffix(offers)


@function_tool
async def get_package_info(context: RunContext[CallState], name: str) -> str:
    """Look up price, included tests, and fasting requirements for a health
    package/bundle by name.

    Args:
        name: The package name, as the caller said it.
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        package = await catalog_repo.find_package(session, name)
        if package is None:
            return f"No package found matching '{name}'."
        offers = await catalog_repo.offers_for_package(session, package.id)
        included_tests = await catalog_repo.get_package_tests(session, package.id)

    result = f"{package.name}: {settings.currency_symbol}{package.price:.2f}."
    if included_tests:
        result += " Includes: " + ", ".join(t.name for t in included_tests) + "."
    if package.value_proposition:
        result += f" {package.value_proposition}"
    if package.fasting_required and package.fasting_instructions:
        result += f" Fasting: {package.fasting_instructions}"
    return result + _offers_suffix(offers)


@function_tool
async def list_offers(context: RunContext[CallState]) -> str:
    """List all currently active promotional offers."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        offers = await catalog_repo.list_active_offers(session)

    if not offers:
        return "No active offers right now."
    return "; ".join(_format_offer(o) for o in offers)


@function_tool
async def suggest_tests_for_symptom(context: RunContext[CallState], symptom: str) -> str:
    """Suggest a relevant screening test or package for a symptom the caller
    mentions (e.g. "fever", "tiredness"). This is a screening suggestion
    only, never a diagnosis -- always remind the caller a doctor should
    interpret any results.

    Args:
        symptom: The symptom or condition the caller mentioned, in their own words.
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        route = await catalog_repo.find_symptom_route(session, symptom)
        if route is None:
            return "No specific screening suggestion for that -- offer to look up a specific test or package by name instead."

        tests = await catalog_repo.find_tests_by_codes(session, route.recommended_test_codes)
        packages = await catalog_repo.find_packages_by_codes(session, route.recommended_package_codes)

    names = [t.name for t in tests] + [p.name for p in packages]
    if not names:
        return "No specific screening suggestion for that -- offer to look up a specific test or package by name instead."

    hint = f" {route.voice_script_hint}" if route.voice_script_hint else ""
    return (
        f"For {symptom}, callers often get screened with: {', '.join(names)}.{hint} "
        "This is a screening suggestion only, not a diagnosis -- a doctor should interpret any results."
    )
