from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from receptionist.db.models import CallEvent


async def record_event(session: AsyncSession, call_session_id: str, event_type: str, payload: dict) -> None:
    session.add(CallEvent(call_session_id=call_session_id, event_type=event_type, payload=payload))
    await session.commit()


async def list_events(
    session: AsyncSession,
    event_type: str | None = None,
    since: datetime | None = None,
    call_session_id: str | None = None,
) -> list[CallEvent]:
    query = select(CallEvent).order_by(CallEvent.created_at)
    if event_type is not None:
        query = query.where(CallEvent.event_type == event_type)
    if since is not None:
        query = query.where(CallEvent.created_at >= since)
    if call_session_id is not None:
        query = query.where(CallEvent.call_session_id == call_session_id)
    result = await session.execute(query)
    return list(result.scalars().all())
