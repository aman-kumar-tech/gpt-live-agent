from __future__ import annotations

from livekit.agents import RunContext
from livekit.agents.llm import function_tool

from receptionist.call_state import CallState
from receptionist.db.engine import get_session_factory
from receptionist.db.repositories import patients as patients_repo
from receptionist.validation import parse_date_of_birth, validate_full_name, validate_phone_number


@function_tool
async def identify_patient(
    context: RunContext[CallState],
    full_name: str,
    phone_number: str,
    date_of_birth: str | None = None,
) -> str:
    """Look up the caller as an existing patient by name and phone number.
    Always call this before discussing anything patient-specific (report
    status, appointments). If no match is found, tell the caller and offer
    to register them as a new patient instead.

    Args:
        full_name: The caller's first AND last name, matched exactly against the record -- a first name alone (e.g. just "Neha") will never match "Neha Gupta". If they only give a first name, ask for their last name too before calling this.
        phone_number: The caller's phone number as plain digits only (e.g. "9812340003"). Ask for just the local number, not "+91"/"+1" etc. -- but if they give a country code anyway, that's fine too, just pass along whatever digits they said (with or without it). No spaces, dashes, or spelled-out words. Convert however the caller said it (spoken digit by digit, grouped like "ninety-eight twelve", or with "double"/"triple"/"oh") into that digit string yourself first.
        date_of_birth: ISO date (YYYY-MM-DD). Only needed if a household shares one phone number and name alone doesn't disambiguate.
    """
    if name_error := validate_full_name(full_name):
        return name_error

    if phone_error := validate_phone_number(phone_number):
        return phone_error

    dob = None
    if date_of_birth:
        dob, dob_error = parse_date_of_birth(date_of_birth)
        if dob_error:
            return dob_error

    session_factory = get_session_factory()
    async with session_factory() as session:
        patient = await patients_repo.find_patient(session, full_name, phone_number, dob)

    if patient is None:
        context.userdata.patient_id = None
        return "No existing patient found with that name and phone number. Offer to register them as a new patient."

    context.userdata.patient_id = str(patient.id)
    return f"Identified patient: {patient.full_name}."
