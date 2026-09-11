"""Shared helpers for the propose -> stage -> interrupt -> commit/abort
pattern used by every write-capable graph. Each graph still owns its own
TypedDict state and node functions -- this just factors out the one piece
that's identical everywhere: pausing for confirmation and resolving the
staged pending_actions row afterwards."""

from __future__ import annotations

from typing import Any
from uuid import UUID

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
