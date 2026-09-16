"""Shared validation for caller-supplied phone numbers and dates of birth.

Centralized here so identify_patient and the registration graph apply the
same rules, and so a malformed value returns a spoken correction instead of
raising an unhandled exception mid-call. This lab's callers are all Indian
mobile numbers -- exactly 10 digits, no country code expected -- but a
caller who includes "91"/"+91" anyway is still accepted, not corrected.
"""

from __future__ import annotations

import re
from datetime import date

from receptionist.clock import lab_today

_PHONE_DIGITS_RE = re.compile(r"^(?:\+?91)?\d{10}$")

MAX_PATIENT_AGE_YEARS = 120


def validate_phone_number(phone_number: str) -> str | None:
    """Returns a spoken error message if invalid, else None.

    Strips every non-digit character, not just whitespace/hyphens/parens/
    periods -- live calls have shown commas ("9812,340003") and a stray
    trailing word STT left untranscribed as a digit ("...four zero zero
    zero three" -> "9812340003 three") in what the model otherwise passed
    through correctly. Matches normalize_phone_digits' leniency (used right
    after this for the actual DB lookup) so a call doesn't get rejected
    here on formatting alone, only to have worked fine there."""
    cleaned = re.sub(r"\D", "", phone_number or "")
    if not _PHONE_DIGITS_RE.match(cleaned):
        return (
            "That doesn't look like a valid phone number -- please give your "
            "10-digit number."
        )
    return None


_PLACEHOLDER_NAMES = {
    "user", "customer", "guest", "caller", "patient", "unknown",
    "anonymous", "n/a", "na", "none", "test", "testing",
    # Conversational filler that can get mistakenly captured as a name --
    # observed live: a caller answering "no, vitamin D" to "what test do you
    # need" led to full_name="No" being registered, since a bare "No" isn't
    # an obviously-fake name like "User"/"Guest" would be, and (since a
    # single word is otherwise a valid name -- see below) nothing else
    # caught it. Rejecting these forces a real re-ask instead.
    "no", "nope", "yes", "yeah", "yep", "ok", "okay", "sure",
    "hi", "hello", "hey", "um", "uh", "hmm",
}


def validate_full_name(full_name: str) -> str | None:
    """Returns a spoken error message if invalid, else None.

    Guards against a placeholder standing in for a name that was never
    actually collected -- observed live: a registration proposed with
    full_name="User" because the caller was never asked, rather than the
    model pausing to ask. A single word is accepted (stored as first_name
    alone, via parse_full_name) -- a caller who only gives one name is not
    forced to invent a last name."""
    cleaned = (full_name or "").strip()
    if not cleaned or cleaned.lower() in _PLACEHOLDER_NAMES:
        return "I don't have your name yet -- could you tell me your name?"
    return None


def parse_full_name(full_name: str) -> tuple[str, str | None, str | None]:
    """Splits a caller-spoken name into (first_name, middle_name, last_name).
    One word -> first_name only. Two words -> first + last. Three or more ->
    first + last from the ends, everything between them joined as middle_name."""
    words = (full_name or "").strip().split()
    if not words:
        return "", None, None
    if len(words) == 1:
        return words[0], None, None
    if len(words) == 2:
        return words[0], None, words[1]
    return words[0], " ".join(words[1:-1]), words[-1]


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

    today = lab_today()
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
