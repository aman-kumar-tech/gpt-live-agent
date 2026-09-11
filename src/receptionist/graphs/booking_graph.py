"""Appointment booking: validate (patient, catalog items, slot availability,
home-collection eligibility, lead time) -> stage -> await confirmation ->
commit/abort.

Pricing here is a straight sum of current catalog prices plus any
home-collection fee from lab_info.operational_rules -- promotional offers
are advisory information surfaced separately via the pricing tools, not
auto-applied at booking time, to keep this v1 graph simple and predictable."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from receptionist.config import settings
from receptionist.db.engine import get_session_factory
from receptionist.db.repositories import appointments as appointments_repo
from receptionist.db.repositories import catalog as catalog_repo
from receptionist.db.repositories import lab_info as lab_info_repo
from receptionist.db.repositories import patients as patients_repo
from receptionist.db.repositories.pending_actions import create_pending_action, get_pending_action
from receptionist.graphs.checkpointer import get_checkpointer
from receptionist.graphs.state import await_confirmation, finalize_pending_action


class BookingState(TypedDict, total=False):
    call_session_id: str
    patient_id: str
    appointment_type: str  # "lab_visit" | "home_collection"
    scheduled_at: str  # ISO datetime
    test_names: list[str]
    package_name: str | None
    address: str | None
    pending_action_id: str | None
    summary: str | None
    confirmed: bool | None
    error: str | None
    appointment_id: str | None
    reference_code: str | None
    total_price: str | None


async def _validate_and_stage(state: BookingState) -> BookingState:
    try:
        scheduled_at = datetime.fromisoformat(state["scheduled_at"])
    except (KeyError, ValueError):
        return {**state, "error": "a valid appointment date/time is required"}

    session_factory = get_session_factory()
    async with session_factory() as session:
        lead_time_hours = await lab_info_repo.get_booking_lead_time_hours(session)
        if scheduled_at < datetime.now() + timedelta(hours=lead_time_hours):
            return {
                **state,
                "error": f"appointments need at least {lead_time_hours} hours' notice -- please choose a later time",
            }

        patient = await patients_repo.get_patient(session, UUID(state["patient_id"]))
        if patient is None:
            return {**state, "error": "patient not found -- identify the caller first"}

        tests = []
        for name in state.get("test_names") or []:
            test = await catalog_repo.find_test(session, name)
            if test is None:
                return {**state, "error": f"no test found matching '{name}'"}
            tests.append(test)

        package = None
        if state.get("package_name"):
            package = await catalog_repo.find_package(session, state["package_name"])
            if package is None:
                return {**state, "error": f"no package found matching '{state['package_name']}'"}

        if not tests and package is None:
            return {**state, "error": "at least one test or package is required"}

        if state.get("appointment_type") == "home_collection":
            if not state.get("address"):
                return {**state, "error": "a home-collection address is required"}
            unavailable = [t.name for t in tests if not t.home_collection_available]
            if unavailable:
                return {**state, "error": f"home collection isn't available for: {', '.join(unavailable)}"}

        if not await appointments_repo.is_slot_available(session, scheduled_at):
            return {**state, "error": "that slot just filled up -- please choose another time"}

        subtotal = sum((t.price for t in tests), Decimal("0"))
        if package is not None:
            subtotal += package.price

        home_collection_fee = Decimal("0")
        if state.get("appointment_type") == "home_collection":
            fee = await lab_info_repo.get_home_collection_fee(session, subtotal)
            home_collection_fee = Decimal(str(fee))
        total = subtotal + home_collection_fee

        payload = {
            "patient_id": state["patient_id"],
            "appointment_type": state["appointment_type"],
            "scheduled_at": state["scheduled_at"],
            "test_ids": [t.id for t in tests],
            "package_id": package.id if package else None,
            "address": state.get("address"),
            "home_collection_fee": str(home_collection_fee),
        }
        action = await create_pending_action(session, state["call_session_id"], "book_appointment", payload)
        await session.commit()

        currency = settings.currency_symbol
        items = [t.name for t in tests] + ([package.name] if package else [])
        summary = (
            f"Book a {state['appointment_type'].replace('_', ' ')} appointment on "
            f"{scheduled_at.strftime('%A, %B %d at %I:%M %p')} for {', '.join(items)}, "
            f"total {currency}{total:.2f}"
        )
        if home_collection_fee:
            summary += f" (includes a {currency}{home_collection_fee:.2f} home collection fee)"
        summary += "."
        if state.get("address"):
            summary += f" Collection address: {state['address']}."
        fasting_notes = [t.fasting_instructions for t in tests if t.fasting_required and t.fasting_instructions]
        if package is not None and package.fasting_required and package.fasting_instructions:
            fasting_notes.append(package.fasting_instructions)
        if fasting_notes:
            summary += " Fasting note: " + " ".join(dict.fromkeys(fasting_notes))

        return {**state, "pending_action_id": str(action.id), "summary": summary, "total_price": str(total)}


def _wait_for_confirmation(state: BookingState) -> BookingState:
    if state.get("error"):
        return state
    confirmed = await_confirmation(state["summary"] or "")
    return {**state, "confirmed": confirmed}


async def _commit_or_abort(state: BookingState) -> BookingState:
    if state.get("error") or not state.get("pending_action_id"):
        return state

    session_factory = get_session_factory()
    async with session_factory() as session:
        if state.get("confirmed"):
            # Use the item ids resolved and locked in at proposal time
            # (pending_actions.payload), not re-resolved from names now.
            pending = await get_pending_action(session, UUID(state["pending_action_id"]))
            payload = pending.payload if pending is not None else {}

            action = await appointments_repo.create_appointment(
                session,
                patient_id=UUID(state["patient_id"]),
                appointment_type=state["appointment_type"],
                scheduled_at=datetime.fromisoformat(state["scheduled_at"]),
                test_ids=payload.get("test_ids") or [],
                package_id=payload.get("package_id"),
                address=state.get("address"),
                home_collection_fee=Decimal(payload.get("home_collection_fee") or "0"),
            )

            await finalize_pending_action(session, state["pending_action_id"], True)
            await session.commit()
            return {**state, "appointment_id": str(action.id), "reference_code": action.reference_code}

        await finalize_pending_action(session, state["pending_action_id"], False)
        await session.commit()
        return state


async def build_booking_graph() -> CompiledStateGraph:
    checkpointer = await get_checkpointer()
    graph = StateGraph(BookingState)
    graph.add_node("validate_and_stage", _validate_and_stage)
    graph.add_node("wait_for_confirmation", _wait_for_confirmation)
    graph.add_node("commit_or_abort", _commit_or_abort)
    graph.add_edge(START, "validate_and_stage")
    graph.add_edge("validate_and_stage", "wait_for_confirmation")
    graph.add_edge("wait_for_confirmation", "commit_or_abort")
    graph.add_edge("commit_or_abort", END)
    return graph.compile(checkpointer=checkpointer)
