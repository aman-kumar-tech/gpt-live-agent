from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from receptionist.db.models import Patient
from receptionist.validation import normalize_phone_digits


async def find_patients_by_phone(session: AsyncSession, phone_number: str) -> list[Patient]:
    """Matches on the last 10 digits, ignoring country code and formatting --
    callers almost never say their own country code, and stored numbers
    aren't consistently formatted either (see normalize_phone_digits)."""
    target = normalize_phone_digits(phone_number)
    result = await session.execute(select(Patient))
    return [p for p in result.scalars().all() if normalize_phone_digits(p.phone_number) == target]


async def find_patient(
    session: AsyncSession,
    full_name: str,
    phone_number: str,
    date_of_birth: date | None = None,
) -> Patient | None:
    """Look up an existing patient. Phone alone isn't unique (shared household
    numbers), so this disambiguates by name, and by DOB if still ambiguous.
    Fails closed: an ambiguous or mismatched DOB means no match, never a
    guess at which same-named household member the caller actually is."""
    candidates = await find_patients_by_phone(session, phone_number)
    name_matches = [p for p in candidates if p.full_name.strip().lower() == full_name.strip().lower()]
    if len(name_matches) <= 1:
        return name_matches[0] if name_matches else None
    if date_of_birth is None:
        return None
    dob_matches = [p for p in name_matches if p.date_of_birth == date_of_birth]
    return dob_matches[0] if len(dob_matches) == 1 else None


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
