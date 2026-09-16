from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from receptionist.db.models import Patient
from receptionist.validation import normalize_phone_digits, parse_full_name


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
    guess at which same-named household member the caller actually is.

    Matches only on the name parts the caller actually gave -- a first name
    alone matches on first_name regardless of last_name, but giving more
    parts (first + last, or first + middle + last) narrows the match
    accordingly. A single word matches either first_name OR last_name (a
    caller who gives just their surname, e.g. "it's Sharma calling", must
    still be found)."""
    candidates = await find_patients_by_phone(session, phone_number)
    first, middle, last = parse_full_name(full_name)

    def _matches(p: Patient) -> bool:
        if middle is None and last is None:
            token = first.strip().lower()
            return token == p.first_name.strip().lower() or token == (p.last_name or "").strip().lower()
        if p.first_name.strip().lower() != first.strip().lower():
            return False
        if last is not None and (p.last_name or "").strip().lower() != last.strip().lower():
            return False
        if middle is not None and (p.middle_name or "").strip().lower() != middle.strip().lower():
            return False
        return True

    name_matches = [p for p in candidates if _matches(p)]
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
    first, middle, last = parse_full_name(full_name)
    patient = Patient(
        first_name=first,
        middle_name=middle,
        last_name=last,
        phone_number=phone_number,
        date_of_birth=date_of_birth,
        gender=gender,
        email=email,
        address=address,
    )
    session.add(patient)
    await session.flush()
    return patient
