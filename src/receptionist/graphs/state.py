"""Shared helpers for the propose -> stage -> interrupt -> commit/abort
pattern used by every write-capable graph. Each graph still owns its own
TypedDict state and node functions -- this just factors out the pieces
that are identical everywhere: pausing for confirmation, resolving the
staged pending_actions row afterwards, and wiring the three nodes into a
graph."""

from __future__ import annotations

from typing import Any, Callable, Coroutine
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from sqlalchemy.ext.asyncio import AsyncSession

from receptionist.db.repositories.pending_actions import resolve_pending_action, get_pending_action


def await_confirmation(summary: str) -> bool:
    """Pauses the graph. The resume value (sent by the confirm_*/discard_*
    tool via Command(resume=...)) is expected to be {"confirmed": bool}."""
    resume_value: dict[str, Any] = interrupt({"summary": summary})
    return bool(resume_value.get("confirmed", False))


async def finalize_pending_action(session: AsyncSession, pending_action_id: str, confirmed: bool) -> None:
    action = await get_pending_action(session, UUID(pending_action_id))
    if action is not None:
        await resolve_pending_action(session, action, "confirmed" if confirmed else "rejected")


def wait_for_confirmation_node(state: dict) -> dict:
    """The middle node of every propose/stage/commit graph: pause for the
    caller's yes/no unless staging already failed. Operates on plain dict
    access so it works against any of the graphs' TypedDict states."""
    if state.get("error"):
        return state
    confirmed = await_confirmation(state.get("summary") or "")
    return {**state, "confirmed": confirmed}


def build_propose_confirm_graph(
    state_cls: type,
    validate_and_stage: Callable[[dict], Coroutine[Any, Any, dict]],
    commit_or_abort: Callable[[dict], Coroutine[Any, Any, dict]],
) -> StateGraph:
    """Builds the linear validate_and_stage -> wait_for_confirmation ->
    commit_or_abort graph shared by booking/registration/cancellation/
    reschedule. Callers still compile() it with their own checkpointer."""
    graph = StateGraph(state_cls)
    graph.add_node("validate_and_stage", validate_and_stage)
    graph.add_node("wait_for_confirmation", wait_for_confirmation_node)
    graph.add_node("commit_or_abort", commit_or_abort)
    graph.add_edge(START, "validate_and_stage")
    graph.add_edge("validate_and_stage", "wait_for_confirmation")
    graph.add_edge("wait_for_confirmation", "commit_or_abort")
    graph.add_edge("commit_or_abort", END)
    return graph
