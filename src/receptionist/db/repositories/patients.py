from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from receptionist.db.models import Patient


async def find_patients_by_phone(session: AsyncSession, phone_number: str) -> list[Patient]:
    result = await session.execute(select(Patient).where(Patient.phone_number == phone_number))
    return list(result.scalars().all())


async def find_patient(
    session: AsyncSession,
    full_name: str,
    phone_number: str,
    date_of_birth: date | None = None,
) -> Patient | None:
    """Look up an existing patient. Phone alone isn't unique (shared household
    numbers), so this disambiguates by name, and by DOB if still ambiguous."""
    candidates = await find_patients_by_phone(session, phone_number)
    name_matches = [p for p in candidates if p.full_name.strip().lower() == full_name.strip().lower()]
    if len(name_matches) == 1:
        return name_matches[0]
    if len(name_matches) > 1 and date_of_birth is not None:
        dob_matches = [p for p in name_matches if p.date_of_birth == date_of_birth]
        if dob_matches:
            return dob_matches[0]
    return name_matches[0] if name_matches else None


async def get_patient(session: AsyncSession, patient_id: UUID) -> Patient | None:
    return await session.get(Patient, patient_id)


async def create_patient(
    session: AsyncSession,
    full_name: str,
    phone_number: str,
    date_of_birth: date | None = None,
    gender: str | None = None,
    email: str | None = None,
    address: str | None = None,
) -> Patient:
    patient = Patient(
        full_name=full_name,
        phone_number=phone_number,
        date_of_birth=date_of_birth,
        gender=gender,
        email=email,
        address=address,
    )
    session.add(patient)
    await session.flush()
    return patient
