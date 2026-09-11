"""Reschedule an existing appointment: ownership check -> new-slot validation
-> stage -> await confirmation -> commit/abort. Commit creates a new
appointment row and marks the old one 'rescheduled' (see
db/repositories/appointments.reschedule_appointment for the trail)."""

from __future__ import annotations

from datetime import datetime
from typing import TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from receptionist.db.engine import get_session_factory
from receptionist.db.models import Appointment
from receptionist.db.repositories import appointments as appointments_repo
from receptionist.db.repositories.pending_actions import create_pending_action, get_pending_action
from receptionist.graphs.checkpointer import get_checkpointer
from receptionist.graphs.state import await_confirmation, finalize_pending_action


class RescheduleState(TypedDict, total=False):
    call_session_id: str
    patient_id: str
    reference_code: str
    new_scheduled_at: str  # ISO datetime
    pending_action_id: str | None
    summary: str | None
    confirmed: bool | None
    error: str | None
    new_appointment_id: str | None
    new_reference_code: str | None


async def _validate_and_stage(state: RescheduleState) -> RescheduleState:
    try:
        new_dt = datetime.fromisoformat(state["new_scheduled_at"])
    except (KeyError, ValueError):
        return {**state, "error": "a valid new date/time is required"}

    session_factory = get_session_factory()
    async with session_factory() as session:
        appointment = await appointments_repo.get_appointment_by_reference(session, state["reference_code"])
        if appointment is None:
            return {**state, "error": f"no appointment found with code {state['reference_code']}"}
        if str(appointment.patient_id) != state["patient_id"]:
            return {**state, "error": "that appointment doesn't belong to this caller"}
        if appointment.status != "booked":
            return {**state, "error": f"that appointment can't be rescheduled (status: {appointment.status})"}
        if not await appointments_repo.is_slot_available(session, new_dt):
            return {**state, "error": "that new slot just filled up -- please choose another time"}

        payload = {"appointment_id": str(appointment.id), "new_scheduled_at": state["new_scheduled_at"]}
        action = await create_pending_action(session, state["call_session_id"], "reschedule_appointment", payload)
        await session.commit()

        old_when = appointment.scheduled_at.strftime("%A, %B %d at %I:%M %p")
        new_when = new_dt.strftime("%A, %B %d at %I:%M %p")
        summary = f"Move appointment {state['reference_code']} from {old_when} to {new_when}."

    return {**state, "pending_action_id": str(action.id), "summary": summary}


def _wait_for_confirmation(state: RescheduleState) -> RescheduleState:
    if state.get("error"):
        return state
    confirmed = await_confirmation(state["summary"] or "")
    return {**state, "confirmed": confirmed}


async def _commit_or_abort(state: RescheduleState) -> RescheduleState:
    if state.get("error") or not state.get("pending_action_id"):
        return state

    session_factory = get_session_factory()
    async with session_factory() as session:
        if state.get("confirmed"):
            pending = await get_pending_action(session, UUID(state["pending_action_id"]))
            result = await session.execute(
                select(Appointment)
                .options(selectinload(Appointment.items))
                .where(Appointment.id == UUID(pending.payload["appointment_id"]))
            )
            old_appointment = result.scalar_one()
            new_dt = datetime.fromisoformat(pending.payload["new_scheduled_at"])
            new_appointment = await appointments_repo.reschedule_appointment(session, old_appointment, new_dt)

            await finalize_pending_action(session, state["pending_action_id"], True)
            await session.commit()
            return {
                **state,
                "new_appointment_id": str(new_appointment.id),
                "new_reference_code": new_appointment.reference_code,
            }

        await finalize_pending_action(session, state["pending_action_id"], False)
        await session.commit()
        return state


async def build_reschedule_graph() -> CompiledStateGraph:
    checkpointer = await get_checkpointer()
    graph = StateGraph(RescheduleState)
    graph.add_node("validate_and_stage", _validate_and_stage)
    graph.add_node("wait_for_confirmation", _wait_for_confirmation)
    graph.add_node("commit_or_abort", _commit_or_abort)
    graph.add_edge(START, "validate_and_stage")
    graph.add_edge("validate_and_stage", "wait_for_confirmation")
    graph.add_edge("wait_for_confirmation", "commit_or_abort")
    graph.add_edge("commit_or_abort", END)
    return graph.compile(checkpointer=checkpointer)
