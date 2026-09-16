"""New-patient registration: validate -> stage -> await confirmation -> commit/abort.
No LLM node -- this is a deterministic state machine; see graphs/state.py for
the shared confirmation-pause helper."""

from __future__ import annotations

from typing import TypedDict

from langgraph.graph.state import CompiledStateGraph

from receptionist.db.engine import get_session_factory
from receptionist.db.repositories import patients as patients_repo
from receptionist.db.repositories.pending_actions import create_pending_action
from receptionist.graphs.checkpointer import get_checkpointer
from receptionist.graphs.state import build_propose_confirm_graph, finalize_pending_action
from receptionist.validation import parse_date_of_birth, validate_full_name, validate_phone_number


class RegistrationState(TypedDict, total=False):
    call_session_id: str
    full_name: str
    phone_number: str
    date_of_birth: str | None
    gender: str | None
    email: str | None
    address: str | None
    pending_action_id: str | None
    summary: str | None
    confirmed: bool | None
    error: str | None
    patient_id: str | None


async def _validate_and_stage(state: RegistrationState) -> RegistrationState:
    if not state.get("full_name") or not state.get("phone_number"):
        return {**state, "error": "full_name and phone_number are required"}

    if name_error := validate_full_name(state["full_name"]):
        return {**state, "error": name_error}

    if phone_error := validate_phone_number(state["phone_number"]):
        return {**state, "error": phone_error}

    dob = None
    if state.get("date_of_birth"):
        dob, dob_error = parse_date_of_birth(state["date_of_birth"])
        if dob_error:
            return {**state, "error": dob_error}

    session_factory = get_session_factory()
    async with session_factory() as session:
        existing = await patients_repo.find_patient(session, state["full_name"], state["phone_number"], dob)
        if existing is not None:
            return {
                **state,
                "error": "a patient with this name and phone number is already registered",
                "patient_id": str(existing.id),
            }

        payload = {
            k: state.get(k)
            for k in ("full_name", "phone_number", "date_of_birth", "gender", "email", "address")
        }
        action = await create_pending_action(session, state["call_session_id"], "register_patient", payload)
        await session.commit()

    summary = f"Register {state['full_name']}, phone number {state['phone_number']}"
    if state.get("date_of_birth"):
        summary += f", date of birth {state['date_of_birth']}"
    summary += "."
    return {**state, "pending_action_id": str(action.id), "summary": summary}


async def _commit_or_abort(state: RegistrationState) -> RegistrationState:
    if state.get("error") or not state.get("pending_action_id"):
        return state

    session_factory = get_session_factory()
    async with session_factory() as session:
        if state.get("confirmed"):
            dob = parse_date_of_birth(state["date_of_birth"])[0] if state.get("date_of_birth") else None
            patient = await patients_repo.create_patient(
                session,
                full_name=state["full_name"],
                phone_number=state["phone_number"],
                date_of_birth=dob,
                gender=state.get("gender"),
                email=state.get("email"),
                address=state.get("address"),
            )
            await finalize_pending_action(session, state["pending_action_id"], True)
            await session.commit()
            return {**state, "patient_id": str(patient.id)}

        await finalize_pending_action(session, state["pending_action_id"], False)
        await session.commit()
        return state


async def build_registration_graph() -> CompiledStateGraph:
    checkpointer = await get_checkpointer()
    graph = build_propose_confirm_graph(RegistrationState, _validate_and_stage, _commit_or_abort)
    return graph.compile(checkpointer=checkpointer)
