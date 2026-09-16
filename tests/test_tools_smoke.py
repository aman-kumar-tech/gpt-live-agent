"""Smoke tests for the @function_tool wrappers, calling the underlying
implementation directly (bypassing LiveKit's tool-calling runtime, which
needs a real AgentSession) with a minimal fake RunContext that only exposes
.userdata -- everything each tool actually touches."""

from dataclasses import dataclass
from typing import Any

from receptionist.call_state import CallState
from receptionist.tools.appointment_tools import (
    confirm_appointment_booking,
    propose_appointment_booking,
)
from receptionist.tools.catalog_tools import (
    get_package_info,
    get_test_info,
    list_offers,
    suggest_tests_for_symptom,
)
from receptionist.tools.identity_tools import identify_patient
from receptionist.tools.lab_info_tools import get_human_handoff_number, get_lab_info
from receptionist.tools.pending_action_tools import discard_pending_action
from receptionist.tools.registration_tools import (
    confirm_new_patient_registration,
    propose_new_patient_registration,
)
from receptionist.tools.report_tools import get_report_status

SEEDED_PATIENT_PHONE = "+919812340001"  # Priya Sharma, seeded from data.json by db/seed.py


@dataclass
class _FakeContext:
    userdata: Any


def _ctx(call_session_id: str = "smoke-test") -> _FakeContext:
    return _FakeContext(userdata=CallState(call_session_id=call_session_id))


async def test_identify_patient_and_get_report_status():
    ctx = _ctx()
    result = await identify_patient._func(ctx, "Priya Sharma", SEEDED_PATIENT_PHONE)
    assert "Priya Sharma" in result
    assert ctx.userdata.patient_id is not None

    status = await get_report_status._func(ctx)
    assert "Vitamin D" in status


async def test_get_report_status_without_identify_first():
    ctx = _ctx()
    result = await get_report_status._func(ctx)
    assert "identify_patient" in result


async def test_identify_patient_refuses_a_different_person_once_caller_is_known():
    # Priya Sharma and Rohan Sharma share SEEDED_PATIENT_PHONE (see
    # test_patient_privacy.py) -- a pre-verified caller (known_full_name from
    # the web form) must not be able to pivot to a household member's own
    # records just by naming them, even sharing that same phone number.
    ctx = _FakeContext(userdata=CallState(call_session_id="smoke-test", known_full_name="Priya Sharma"))
    result = await identify_patient._func(ctx, "Rohan Sharma", SEEDED_PATIENT_PHONE)
    assert "already identified as Priya Sharma" in result
    assert ctx.userdata.patient_id is None

    # The known caller identifying themselves (even a shorter form of their
    # own name) must still work normally.
    result = await identify_patient._func(ctx, "Priya", SEEDED_PATIENT_PHONE)
    assert "Priya Sharma" in result
    assert ctx.userdata.patient_id is not None


async def test_catalog_lookups():
    ctx = _ctx()
    assert "₹350.00" in await get_test_info._func(ctx, "CBC")
    assert "₹1999.00" in await get_package_info._func(ctx, "SwasthFit Super 1")
    assert await list_offers._func(ctx)


async def test_lab_info_tools():
    ctx = _ctx()
    info = await get_lab_info._func(ctx)
    assert "Dr Lal PathLabs" in info

    number = await get_human_handoff_number._func(ctx)
    assert number == "+918071371386"


async def test_suggest_tests_for_symptom():
    ctx = _ctx()
    result = await suggest_tests_for_symptom._func(ctx, "fever")
    assert "not a diagnosis" in result
    assert "CBC" in result or "Complete Blood Count" in result or "Fever Panel" in result


async def test_registration_propose_then_confirm_via_tools():
    import uuid

    ctx = _ctx()
    phone = f"9{uuid.uuid4().int % 10**9:09d}"

    proposal = await propose_new_patient_registration._func(ctx, "Tool Smoke Test", phone)
    assert "Should I go ahead?" in proposal
    assert ctx.userdata.pending_kind == "registration"

    confirmation = await confirm_new_patient_registration._func(ctx)
    assert "confirmed" in confirmation.lower()
    assert ctx.userdata.pending_kind is None
    assert ctx.userdata.patient_id is not None


async def test_booking_propose_then_discard_via_tools():
    from datetime import datetime, timedelta

    ctx = _ctx()
    identify_result = await identify_patient._func(ctx, "Priya Sharma", SEEDED_PATIENT_PHONE)
    assert ctx.userdata.patient_id is not None

    scheduled_at = datetime.now() + timedelta(days=500, minutes=17)
    proposal = await propose_appointment_booking._func(
        ctx, "lab_visit", scheduled_at.isoformat(), test_names=["CBC"]
    )
    assert "Should I go ahead?" in proposal
    assert ctx.userdata.pending_kind == "booking"

    discard_result = await discard_pending_action._func(ctx)
    assert "discarded" in discard_result.lower()
    assert ctx.userdata.pending_kind is None

    confirm_again = await confirm_appointment_booking._func(ctx)
    assert "no pending booking" in confirm_again.lower()
