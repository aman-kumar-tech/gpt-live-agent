"""Cancel an existing appointment: ownership check -> stage -> await
confirmation -> commit/abort."""

from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from receptionist.db.engine import get_session_factory
from receptionist.db.repositories import appointments as appointments_repo
from receptionist.db.repositories.pending_actions import create_pending_action
from receptionist.graphs.checkpointer import get_checkpointer
from receptionist.graphs.state import await_confirmation, finalize_pending_action


class CancellationState(TypedDict, total=False):
    call_session_id: str
    patient_id: str
    reference_code: str
    reason: str | None
    pending_action_id: str | None
    summary: str | None
    confirmed: bool | None
    error: str | None
    cancelled: bool | None


async def _validate_and_stage(state: CancellationState) -> CancellationState:
    session_factory = get_session_factory()
    async with session_factory() as session:
        appointment = await appointments_repo.get_appointment_by_reference(session, state["reference_code"])
        if appointment is None:
            return {**state, "error": f"no appointment found with code {state['reference_code']}"}
        if str(appointment.patient_id) != state["patient_id"]:
            return {**state, "error": "that appointment doesn't belong to this caller"}
        if appointment.status != "booked":
            return {**state, "error": f"that appointment can't be cancelled (status: {appointment.status})"}

        payload = {"appointment_id": str(appointment.id), "reason": state.get("reason")}
        action = await create_pending_action(session, state["call_session_id"], "cancel_appointment", payload)
        await session.commit()

        when = appointment.scheduled_at.strftime("%A, %B %d at %I:%M %p")
        summary = f"Cancel appointment {state['reference_code']} scheduled for {when}."

    return {**state, "pending_action_id": str(action.id), "summary": summary}


def _wait_for_confirmation(state: CancellationState) -> CancellationState:
    if state.get("error"):
        return state
    confirmed = await_confirmation(state["summary"] or "")
    return {**state, "confirmed": confirmed}


async def _commit_or_abort(state: CancellationState) -> CancellationState:
    if state.get("error") or not state.get("pending_action_id"):
        return state

    session_factory = get_session_factory()
    async with session_factory() as session:
        if state.get("confirmed"):
            appointment = await appointments_repo.get_appointment_by_reference(session, state["reference_code"])
            await appointments_repo.cancel_appointment(session, appointment)

            await finalize_pending_action(session, state["pending_action_id"], True)
            await session.commit()
            return {**state, "cancelled": True}

        await finalize_pending_action(session, state["pending_action_id"], False)
        await session.commit()
        return state


async def build_cancellation_graph() -> CompiledStateGraph:
    checkpointer = await get_checkpointer()
    graph = StateGraph(CancellationState)
    graph.add_node("validate_and_stage", _validate_and_stage)
    graph.add_node("wait_for_confirmation", _wait_for_confirmation)
    graph.add_node("commit_or_abort", _commit_or_abort)
    graph.add_edge(START, "validate_and_stage")
    graph.add_edge("validate_and_stage", "wait_for_confirmation")
    graph.add_edge("wait_for_confirmation", "commit_or_abort")
    graph.add_edge("commit_or_abort", END)
    return graph.compile(checkpointer=checkpointer)
