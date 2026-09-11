from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from receptionist.db.models import PendingAction


async def create_pending_action(
    session: AsyncSession,
    call_session_id: str,
    action_type: str,
    payload: dict,
) -> PendingAction:
    action = PendingAction(call_session_id=call_session_id, action_type=action_type, payload=payload)
    session.add(action)
    await session.flush()
    return action


async def get_pending_action(session: AsyncSession, action_id: UUID) -> PendingAction | None:
    return await session.get(PendingAction, action_id)


async def get_active_pending_action(session: AsyncSession, call_session_id: str) -> PendingAction | None:
    result = await session.execute(
        select(PendingAction)
        .where(
            PendingAction.call_session_id == call_session_id,
            PendingAction.status == "proposed",
            PendingAction.expires_at > datetime.now(),
        )
        .order_by(PendingAction.created_at.desc())
    )
    return result.scalars().first()


async def resolve_pending_action(session: AsyncSession, action: PendingAction, status: str) -> PendingAction:
    action.status = status
    action.resolved_at = func.now()
    await session.flush()
    return action
