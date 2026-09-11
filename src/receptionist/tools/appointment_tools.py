from __future__ import annotations

import uuid
from datetime import date as date_cls
from datetime import time

from langgraph.types import Command
from livekit.agents import RunContext
from livekit.agents.llm import function_tool

from receptionist.call_state import CallState
from receptionist.db.engine import get_session_factory
from receptionist.db.repositories import appointments as appointments_repo
from receptionist.db.repositories import lab_info as lab_info_repo

_WEEKDAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


@function_tool
async def check_appointment_availability(context: RunContext[CallState], on_date: str) -> str:
    """List open appointment slots on a given day, within the lab's opening
    hours for that day.

    Args:
        on_date: ISO date (YYYY-MM-DD) the caller wants to come in.
    """
    day = date_cls.fromisoformat(on_date)
    session_factory = get_session_factory()
    async with session_factory() as session:
        lab = await lab_info_repo.get_lab_info(session)
        if lab is None:
            return "Lab hours are not configured."

        hours = lab.hours.get(_WEEKDAY_KEYS[day.weekday()]) or {}
        if not hours.get("open") or not hours.get("close"):
            return f"The lab is closed on {day.strftime('%A')}."

        open_time = time.fromisoformat(hours["open"])
        close_time = time.fromisoformat(hours["close"])
        slots = await appointments_repo.list_open_slots(session, day, open_time, close_time)

    if not slots:
        return f"No open slots on {day.strftime('%A, %B %d')}."
    return ", ".join(s.strftime("%I:%M %p") for s in slots)


@function_tool
async def list_my_appointments(context: RunContext[CallState]) -> str:
    """List the identified caller's upcoming booked appointments, including
    each one's reference code (needed to reschedule or cancel it). Requires
    identify_patient to have been called first."""
    patient_id = context.userdata.patient_id
    if patient_id is None:
        return "The caller hasn't been identified yet. Call identify_patient first."

    session_factory = get_session_factory()
    async with session_factory() as session:
        appointments = await appointments_repo.list_upcoming_for_patient(session, uuid.UUID(patient_id))

    if not appointments:
        return "No upcoming appointments found."

    lines = []
    for a in appointments:
        items = ", ".join(i.test.name if i.test else i.package.name for i in a.items if i.test or i.package)
        lines.append(
            f"{a.reference_code}: {a.type.replace('_', ' ')} on {a.scheduled_at.strftime('%A, %B %d at %I:%M %p')} ({items})"
        )
    return "; ".join(lines)


@function_tool
async def propose_appointment_booking(
    context: RunContext[CallState],
    appointment_type: str,
    scheduled_at: str,
    test_names: list[str] | None = None,
    package_name: str | None = None,
    address: str | None = None,
) -> str:
    """Propose booking a new appointment. Does NOT book it yet -- read the
    date/time, tests/package, and total price back to the caller, and only
    call confirm_appointment_booking after they explicitly say yes.
    Requires identify_patient to have been called first.

    Args:
        appointment_type: Either "lab_visit" or "home_collection".
        scheduled_at: ISO datetime (YYYY-MM-DDTHH:MM:SS) for the appointment, chosen from check_appointment_availability.
        test_names: Names of individual tests to book, if any.
        package_name: Name of a health package to book, if any.
        address: Required if appointment_type is "home_collection".
    """
    if context.userdata.patient_id is None:
        return "The caller hasn't been identified yet. Call identify_patient first."

    graph = await context.userdata.get_graph("booking")
    thread_id = str(uuid.uuid4())
    result = await graph.ainvoke(
        {
            "call_session_id": context.userdata.call_session_id,
            "patient_id": context.userdata.patient_id,
            "appointment_type": appointment_type,
            "scheduled_at": scheduled_at,
            "test_names": test_names or [],
            "package_name": package_name,
            "address": address,
        },
        config={"configurable": {"thread_id": thread_id}},
    )
    if "__interrupt__" in result:
        context.userdata.set_pending("booking", thread_id)
        return result["__interrupt__"][0].value["summary"] + " Should I go ahead?"
    return result.get("error") or "Could not propose that booking."


@function_tool
async def confirm_appointment_booking(context: RunContext[CallState]) -> str:
    """Confirm and finalize the pending appointment booking. Only call this
    after the caller has explicitly said yes to the read-back."""
    if context.userdata.pending_kind != "booking" or not context.userdata.pending_thread_id:
        return "There is no pending booking to confirm."

    graph = await context.userdata.get_graph("booking")
    result = await graph.ainvoke(
        Command(resume={"confirmed": True}),
        config={"configurable": {"thread_id": context.userdata.pending_thread_id}},
    )
    context.userdata.clear_pending()

    if result.get("reference_code"):
        return f"Booking confirmed. Your confirmation code is {result['reference_code']}."
    return result.get("error") or "Could not complete the booking."


@function_tool
async def propose_appointment_change(context: RunContext[CallState], reference_code: str, new_scheduled_at: str) -> str:
    """Propose moving an existing appointment to a new date/time. Does NOT
    change it yet -- read the old and new times back, and only call
    confirm_appointment_change after the caller explicitly says yes.

    Args:
        reference_code: The appointment's confirmation code.
        new_scheduled_at: ISO datetime (YYYY-MM-DDTHH:MM:SS) for the new time, chosen from check_appointment_availability.
    """
    if context.userdata.patient_id is None:
        return "The caller hasn't been identified yet. Call identify_patient first."

    graph = await context.userdata.get_graph("reschedule")
    thread_id = str(uuid.uuid4())
    result = await graph.ainvoke(
        {
            "call_session_id": context.userdata.call_session_id,
            "patient_id": context.userdata.patient_id,
            "reference_code": reference_code,
            "new_scheduled_at": new_scheduled_at,
        },
        config={"configurable": {"thread_id": thread_id}},
    )
    if "__interrupt__" in result:
        context.userdata.set_pending("reschedule", thread_id)
        return result["__interrupt__"][0].value["summary"] + " Should I go ahead?"
    return result.get("error") or "Could not propose that change."


@function_tool
async def confirm_appointment_change(context: RunContext[CallState]) -> str:
    """Confirm and finalize the pending appointment reschedule. Only call
    this after the caller has explicitly said yes to the read-back."""
    if context.userdata.pending_kind != "reschedule" or not context.userdata.pending_thread_id:
        return "There is no pending reschedule to confirm."

    graph = await context.userdata.get_graph("reschedule")
    result = await graph.ainvoke(
        Command(resume={"confirmed": True}),
        config={"configurable": {"thread_id": context.userdata.pending_thread_id}},
    )
    context.userdata.clear_pending()

    if result.get("new_reference_code"):
        return f"Appointment moved. Your new confirmation code is {result['new_reference_code']}."
    return result.get("error") or "Could not complete the reschedule."


@function_tool
async def propose_appointment_cancellation(context: RunContext[CallState], reference_code: str, reason: str | None = None) -> str:
    """Propose cancelling an existing appointment. Does NOT cancel it yet --
    read back which appointment would be cancelled, and only call
    confirm_appointment_cancellation after the caller explicitly says yes.

    Args:
        reference_code: The appointment's confirmation code.
        reason: The caller's stated reason, if any.
    """
    if context.userdata.patient_id is None:
        return "The caller hasn't been identified yet. Call identify_patient first."

    graph = await context.userdata.get_graph("cancellation")
    thread_id = str(uuid.uuid4())
    result = await graph.ainvoke(
        {
            "call_session_id": context.userdata.call_session_id,
            "patient_id": context.userdata.patient_id,
            "reference_code": reference_code,
            "reason": reason,
        },
        config={"configurable": {"thread_id": thread_id}},
    )
    if "__interrupt__" in result:
        context.userdata.set_pending("cancellation", thread_id)
        return result["__interrupt__"][0].value["summary"] + " Should I go ahead?"
    return result.get("error") or "Could not propose that cancellation."


@function_tool
async def confirm_appointment_cancellation(context: RunContext[CallState]) -> str:
    """Confirm and finalize the pending appointment cancellation. Only call
    this after the caller has explicitly said yes to the read-back."""
    if context.userdata.pending_kind != "cancellation" or not context.userdata.pending_thread_id:
        return "There is no pending cancellation to confirm."

    graph = await context.userdata.get_graph("cancellation")
    result = await graph.ainvoke(
        Command(resume={"confirmed": True}),
        config={"configurable": {"thread_id": context.userdata.pending_thread_id}},
    )
    context.userdata.clear_pending()

    if result.get("cancelled"):
        return "Cancellation confirmed."
    return result.get("error") or "Could not complete the cancellation."
