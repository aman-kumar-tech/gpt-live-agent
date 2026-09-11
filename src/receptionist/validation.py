"""Shared validation for caller-supplied phone numbers and dates of birth.

Centralized here so identify_patient and the registration graph apply the
same rules, and so a malformed value returns a spoken correction instead of
raising an unhandled exception mid-call. Phone format is deliberately
permissive (E.164-ish, not bound to one country) since callers may say
numbers in Indian, ITU, or local formats.
"""

from __future__ import annotations

import re
from datetime import date, datetime

_PHONE_DIGITS_RE = re.compile(r"^\+?\d{7,15}$")

MAX_PATIENT_AGE_YEARS = 120


def validate_phone_number(phone_number: str) -> str | None:
    """Returns a spoken error message if invalid, else None."""
    cleaned = re.sub(r"[\s\-().]", "", phone_number or "")
    if not _PHONE_DIGITS_RE.match(cleaned):
        return (
            "That doesn't look like a valid phone number -- please give a number "
            "with 7 to 15 digits, optionally starting with a country code."
        )
    return None


def parse_date_of_birth(date_of_birth: str) -> tuple[date | None, str | None]:
    """Parses an ISO (YYYY-MM-DD) date of birth. Returns (date, None) on
    success, or (None, spoken error message) if the string is malformed, in
    the future, or implies an unreasonable age."""
    try:
        dob = date.fromisoformat(date_of_birth)
    except ValueError:
        return None, "That date of birth doesn't look valid -- please give it as year, month, day."

    today = datetime.now().date()
    if dob > today:
        return None, "That date of birth is in the future -- could you double-check it?"

    age_years = (today - dob).days / 365.25
    if age_years > MAX_PATIENT_AGE_YEARS:
        return (
            None,
            f"That date of birth would make the patient over {MAX_PATIENT_AGE_YEARS} years "
            "old -- could you double-check it?",
        )

    return dob, None
