from __future__ import annotations

from livekit.agents import RunContext
from livekit.agents.llm import function_tool

from receptionist.call_state import CallState
from receptionist.db.engine import get_session_factory
from receptionist.db.repositories import patients as patients_repo
from receptionist.validation import parse_date_of_birth, validate_full_name, validate_phone_number


def _is_known_caller(requested_name: str, known_full_name: str) -> bool:
    """First-name, case-insensitive match -- good enough to tell "the known
    caller, however much of their name was given" apart from "a different
    person the caller is asking about", without requiring an exact string
    match against however much of their own name they happened to state."""
    return requested_name.strip().split()[0].lower() == known_full_name.strip().split()[0].lower()


@function_tool
async def check_phone_number(context: RunContext[CallState], phone_number: str | None = None) -> str:
    """Validate a phone number the moment the caller states it -- for
    identification, registration, or anything else that will need one.
    Call this right then, before collecting anything else, so a bad number
    (wrong digit count, garbled by misheard speech, etc.) gets caught and
    the caller asked again immediately -- not discovered later as a side
    effect of identify_patient or a registration/booking tool, after
    something else has already been collected too.

    Args:
        phone_number: Plain digits, converted from however the caller said it -- see identify_patient's phone_number argument for the conversion rules (spoken digit by digit, grouped, "double"/"triple"/"oh", etc.). Omit this if the caller's phone number was already provided before the call started (you'll be told so) -- it's used automatically.
    """
    phone_number = phone_number or context.userdata.known_phone_number
    if error := validate_phone_number(phone_number or ""):
        return error
    return "That phone number looks valid."


@function_tool
async def identify_patient(
    context: RunContext[CallState],
    full_name: str | None = None,
    phone_number: str | None = None,
    date_of_birth: str | None = None,
) -> str:
    """Look up the caller as an existing patient by name and phone number.
    Always call this before discussing anything patient-specific (report
    status, appointments). If no match is found, tell the caller and offer
    to register them as a new patient instead.

    Args:
        full_name: The caller's own name, as much of it as they give. A first name alone (e.g. just "Neha") is enough to call this, but matches more loosely -- if it turns up more than one person and no date of birth resolves it, ask for their last name too and call this again. Omit this if the caller's name was already provided before the call started (you'll be told so) -- it's used automatically. Never pass a different person's name here (see below).
        phone_number: The caller's phone number as plain digits only (e.g. "9812340003"). Ask for just the local number, not "+91"/"+1" etc. -- but if they give a country code anyway, that's fine too, just pass along whatever digits they said (with or without it). No spaces, dashes, or spelled-out words. Convert however the caller said it (spoken digit by digit, grouped like "ninety-eight twelve", or with "double"/"triple"/"oh") into that digit string yourself first. Omit this if the caller's phone number was already provided before the call started (you'll be told so) -- it's used automatically.
        date_of_birth: ISO date (YYYY-MM-DD). Only needed if a household shares one phone number and name alone doesn't disambiguate.
    """
    requested_name = full_name or context.userdata.known_full_name
    known_name = context.userdata.known_full_name
    if known_name and requested_name and not _is_known_caller(requested_name, known_name):
        # The caller's own identity for this call was already verified via
        # the web form before the call connected -- that's a stronger
        # guarantee than anything said mid-call, so it's never overridden by
        # a different name spoken during the call, even sharing the same
        # phone number (a real scenario: household members often do). A
        # different person's records require them to call in and be
        # verified themselves, not a name the current caller happens to say.
        return (
            f"This call is already identified as {known_name}. For privacy, do not look "
            "up or discuss another person's records during this call, even if they share "
            "this phone number -- tell the caller that person needs to call in themselves."
        )

    full_name = requested_name
    phone_number = phone_number or context.userdata.known_phone_number

    if name_error := validate_full_name(full_name or ""):
        return name_error

    if phone_error := validate_phone_number(phone_number or ""):
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
