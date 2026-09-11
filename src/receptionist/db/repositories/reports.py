from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from receptionist.db.models import Report


async def list_reports_for_patient(session: AsyncSession, patient_id: UUID) -> list[Report]:
    result = await session.execute(
        select(Report)
        .options(selectinload(Report.test), selectinload(Report.package))
        .where(Report.patient_id == patient_id)
        .order_by(Report.created_at.desc())
    )
    return list(result.scalars().all())
