import secrets
import string
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from receptionist.clock import lab_now
from receptionist.db.models import Appointment, AppointmentItem

# Simple constant-capacity heuristic for v1 (no dedicated slots/capacity
# table) -- a known simplification, see plan risk #7.
SLOT_MINUTES = 60
MAX_CONCURRENT_PER_SLOT = 3
_CODE_ALPHABET = "".join(c for c in string.ascii_uppercase + string.digits if c not in "0O1I")


def _generate_reference_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))


async def _count_booked_at(session: AsyncSession, scheduled_at: datetime) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(Appointment)
        .where(
            Appointment.scheduled_at == scheduled_at,
            Appointment.status == "booked",
        )
    )
    return result.scalar_one()


async def is_slot_available(session: AsyncSession, scheduled_at: datetime) -> bool:
    count = await _count_booked_at(session, scheduled_at)
    return count < MAX_CONCURRENT_PER_SLOT


async def list_open_slots(
    session: AsyncSession,
    on_date: date,
    open_time: time,
    close_time: time,
    lead_time_hours: float = 0,
) -> list[datetime]:
    """Candidate hourly slots for a given day, filtered to ones that still
    have capacity AND meet the lab's booking lead time -- otherwise this
    would offer a slot (e.g. today's opening time) that propose_appointment_
    booking then turns around and rejects as too soon."""
    slots: list[datetime] = []
    earliest = lab_now() + timedelta(hours=lead_time_hours)
    current = datetime.combine(on_date, open_time)
    end = datetime.combine(on_date, close_time)
    while current < end:
        if current >= earliest and await is_slot_available(session, current):
            slots.append(current)
        current += timedelta(minutes=SLOT_MINUTES)
    return slots


async def create_appointment(
    session: AsyncSession,
    patient_id: UUID,
    appointment_type: str,
    scheduled_at: datetime,
    test_ids: list[int] | None = None,
    package_id: int | None = None,
    address: str | None = None,
    home_collection_fee: Decimal = Decimal("0"),
    notes: str | None = None,
    previous_appointment_id: UUID | None = None,
) -> Appointment:
    appointment = Appointment(
        reference_code=_generate_reference_code(),
        patient_id=patient_id,
        type=appointment_type,
        status="booked",
        scheduled_at=scheduled_at,
        address=address,
        home_collection_fee=home_collection_fee,
        notes=notes,
        previous_appointment_id=previous_appointment_id,
    )
    session.add(appointment)
    await session.flush()

    for test_id in test_ids or []:
        session.add(AppointmentItem(appointment_id=appointment.id, test_id=test_id))
    if package_id is not None:
        session.add(AppointmentItem(appointment_id=appointment.id, package_id=package_id))
    await session.flush()
    return appointment


async def get_appointment_by_reference(session: AsyncSession, reference_code: str) -> Appointment | None:
    result = await session.execute(
        select(Appointment).where(Appointment.reference_code == reference_code.strip().upper())
    )
    return result.scalar_one_or_none()


async def list_upcoming_for_patient(session: AsyncSession, patient_id: UUID) -> list[Appointment]:
    result = await session.execute(
        select(Appointment)
        .options(selectinload(Appointment.items).selectinload(AppointmentItem.test), selectinload(Appointment.items).selectinload(AppointmentItem.package))
        .where(
            Appointment.patient_id == patient_id,
            Appointment.status.in_(("booked",)),
            Appointment.scheduled_at >= lab_now(),
        )
        .order_by(Appointment.scheduled_at)
    )
    return list(result.scalars().all())


async def reschedule_appointment(
    session: AsyncSession,
    old_appointment: Appointment,
    new_scheduled_at: datetime,
) -> Appointment:
    """Supersedes the old row (status=rescheduled) and creates a new booked
    row linked via previous_appointment_id, preserving a reschedule trail."""
    old_appointment.status = "rescheduled"
    new_appointment = await create_appointment(
        session,
        patient_id=old_appointment.patient_id,
        appointment_type=old_appointment.type,
        scheduled_at=new_scheduled_at,
        address=old_appointment.address,
        home_collection_fee=old_appointment.home_collection_fee,
        notes=old_appointment.notes,
        previous_appointment_id=old_appointment.id,
    )
    for item in old_appointment.items:
        session.add(AppointmentItem(appointment_id=new_appointment.id, test_id=item.test_id, package_id=item.package_id))
    await session.flush()
    return new_appointment


async def cancel_appointment(session: AsyncSession, appointment: Appointment) -> Appointment:
    appointment.status = "cancelled"
    await session.flush()
    return appointment
