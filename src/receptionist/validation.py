"""Shared validation for caller-supplied phone numbers and dates of birth.

Centralized here so identify_patient and the registration graph apply the
same rules, and so a malformed value returns a spoken correction instead of
raising an unhandled exception mid-call. This lab's callers are all Indian
mobile numbers -- exactly 10 digits, no country code expected -- but a
caller who includes "91"/"+91" anyway is still accepted, not corrected.
"""

from __future__ import annotations

import re
from datetime import date, datetime

_PHONE_DIGITS_RE = re.compile(r"^(?:\+?91)?\d{10}$")

MAX_PATIENT_AGE_YEARS = 120


def validate_phone_number(phone_number: str) -> str | None:
    """Returns a spoken error message if invalid, else None."""
    cleaned = re.sub(r"[\s\-().]", "", phone_number or "")
    if not _PHONE_DIGITS_RE.match(cleaned):
        return (
            "That doesn't look like a valid phone number -- please give your "
            "10-digit number."
        )
    return None


_PLACEHOLDER_NAMES = {
    "user", "customer", "guest", "caller", "patient", "unknown",
    "anonymous", "n/a", "na", "none", "test", "testing",
}


def validate_full_name(full_name: str) -> str | None:
    """Returns a spoken error message if invalid, else None.

    Guards against a placeholder standing in for a name that was never
    actually collected -- observed live: a registration proposed with
    full_name="User" because the caller was never asked, rather than the
    model pausing to ask. Also requires a first AND last name, since every
    name match in this app (identify_patient, duplicate-registration check)
    is exact-string against "first last" -- a single name can never match."""
    cleaned = (full_name or "").strip()
    if not cleaned or cleaned.lower() in _PLACEHOLDER_NAMES:
        return "I don't have your name yet -- could you tell me your full first and last name?"
    if len(cleaned.split()) < 2:
        return "Could I get your last name as well, so I have your full name on file?"
    return None


def normalize_phone_digits(phone_number: str) -> str:
    """Digits only, last 10 -- so a caller-stated local number (no country
    code) still matches a stored E.164 value, and formatting differences
    between the two (spaces, dashes, a leading country code or not) don't
    matter. Local mobile numbers are 10 digits in both the seed data's
    countries (India, US), so this is a safe general comparison key here."""
    digits = re.sub(r"\D", "", phone_number or "")
    return digits[-10:] if len(digits) >= 10 else digits


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
