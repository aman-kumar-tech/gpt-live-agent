"""Household phone-sharing is a real scenario in the seed data (Priya Sharma
and Rohan Sharma share one number), so identify_patient's disambiguation
must fail closed -- an ambiguous or wrong date of birth must never resolve
to a guess at which household member is actually calling."""

import uuid
from datetime import date

from receptionist.db.engine import get_session_factory
from receptionist.db.repositories.patients import create_patient, find_patient

SEEDED_HOUSEHOLD_PHONE = "+919812340001"  # Priya Sharma + Rohan Sharma, from data.json


async def test_find_patient_disambiguates_household_by_name():
    session_factory = get_session_factory()
    async with session_factory() as session:
        priya = await find_patient(session, "Priya Sharma", SEEDED_HOUSEHOLD_PHONE)
        rohan = await find_patient(session, "Rohan Sharma", SEEDED_HOUSEHOLD_PHONE)

    assert priya is not None and rohan is not None
    assert priya.id != rohan.id


async def test_find_patient_rejects_unregistered_name_on_shared_phone():
    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await find_patient(session, "Someone Else Entirely", SEEDED_HOUSEHOLD_PHONE)
    assert result is None


async def test_find_patient_fails_closed_on_duplicate_name_without_dob():
    phone = f"+1555{uuid.uuid4().int % 10_000_000:07d}"
    session_factory = get_session_factory()
    async with session_factory() as session:
        await create_patient(session, full_name="Dup Twin", phone_number=phone, date_of_birth=date(1990, 1, 1))
        await create_patient(session, full_name="Dup Twin", phone_number=phone, date_of_birth=date(1995, 6, 15))
        await session.commit()

        # same name, no DOB to disambiguate -- must not guess either twin
        result = await find_patient(session, "Dup Twin", phone)
    assert result is None


async def test_find_patient_fails_closed_on_duplicate_name_with_wrong_dob():
    phone = f"+1555{uuid.uuid4().int % 10_000_000:07d}"
    session_factory = get_session_factory()
    async with session_factory() as session:
        await create_patient(session, full_name="Dup Twin", phone_number=phone, date_of_birth=date(1990, 1, 1))
        await create_patient(session, full_name="Dup Twin", phone_number=phone, date_of_birth=date(1995, 6, 15))
        await session.commit()

        # a DOB that matches neither twin must not fall back to an arbitrary one
        result = await find_patient(session, "Dup Twin", phone, date(2000, 12, 31))
    assert result is None


async def test_find_patient_resolves_duplicate_name_with_correct_dob():
    phone = f"+1555{uuid.uuid4().int % 10_000_000:07d}"
    session_factory = get_session_factory()
    async with session_factory() as session:
        first = await create_patient(session, full_name="Dup Twin", phone_number=phone, date_of_birth=date(1990, 1, 1))
        await create_patient(session, full_name="Dup Twin", phone_number=phone, date_of_birth=date(1995, 6, 15))
        await session.commit()

        result = await find_patient(session, "Dup Twin", phone, date(1990, 1, 1))
    assert result is not None
    assert result.id == first.id
