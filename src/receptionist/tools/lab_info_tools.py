from __future__ import annotations

from livekit.agents import RunContext
from livekit.agents.llm import function_tool

from receptionist.call_state import CallState
from receptionist.db.engine import get_session_factory
from receptionist.db.repositories import lab_info as lab_info_repo

_DAY_ORDER = [("mon", "Mon"), ("tue", "Tue"), ("wed", "Wed"), ("thu", "Thu"), ("fri", "Fri"), ("sat", "Sat"), ("sun", "Sun")]


def _format_hours(hours: dict) -> str:
    parts = []
    for key, label in _DAY_ORDER:
        day = hours.get(key) or {}
        if day.get("open") and day.get("close"):
            parts.append(f"{label} {day['open']}-{day['close']}")
        else:
            parts.append(f"{label} closed")
    return ", ".join(parts)


def format_lab_info(lab) -> str:
    if lab is None:
        return "Lab info is not configured."
    result = f"{lab.name}, {lab.address}. Phone {lab.phone_number}. Hours: {_format_hours(lab.hours)}."
    metadata = lab.metadata_ or {}

    accreditations = metadata.get("accreditations")
    if accreditations:
        result += f" Accredited: {', '.join(accreditations)}."

    facilities = metadata.get("facilities") or {}
    if facilities.get("parking"):
        result += f" Parking: {facilities['parking']}."
    if "home_collection" in facilities:
        result += f" Home collection: {'available' if facilities['home_collection'] else 'not available'}."
    if "wheelchair_accessible" in facilities:
        result += f" Wheelchair accessible: {'yes' if facilities['wheelchair_accessible'] else 'no'}."

    payment_methods = metadata.get("payment_methods_accepted")
    if payment_methods:
        result += f" Payment methods accepted: {', '.join(payment_methods)}."

    return result


@function_tool
async def get_lab_info(context: RunContext[CallState]) -> str:
    """Get the lab's real address, phone number, hours, accreditations,
    facilities (parking, home collection, wheelchair access), and accepted
    payment methods. You'll normally already have this from the lab facts
    given to you at the start of the call -- only call this if that's
    missing or you need to double-check it. Speak only the address itself --
    never give turn-by-turn directions; tell the caller to use their own
    maps app if they ask how to get there."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        lab = await lab_info_repo.get_lab_info(session)
    return format_lab_info(lab)


@function_tool
async def get_human_handoff_number(context: RunContext[CallState]) -> str:
    """Get the lab's real phone number to give a caller who needs a human.
    Use this when the caller asks for a person, or asks for something
    outside what you can do -- state plainly that you can't transfer the
    call yourself and give them this number to call."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        lab = await lab_info_repo.get_lab_info(session)

    if lab is None:
        return "No handoff number is configured."
    return lab.phone_number
