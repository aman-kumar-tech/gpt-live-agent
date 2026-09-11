from __future__ import annotations

from livekit.agents import Agent
from livekit.plugins.openai.realtime import GPTLiveModel

from receptionist.config import settings
from receptionist.instructions import build_reasoning_instructions, build_voice_instructions
from receptionist.tools.appointment_tools import (
    check_appointment_availability,
    confirm_appointment_booking,
    confirm_appointment_cancellation,
    confirm_appointment_change,
    list_my_appointments,
    propose_appointment_booking,
    propose_appointment_cancellation,
    propose_appointment_change,
)
from receptionist.tools.catalog_tools import get_package_info, get_test_info, list_offers, suggest_tests_for_symptom
from receptionist.tools.identity_tools import identify_patient
from receptionist.tools.lab_info_tools import get_human_handoff_number, get_lab_info
from receptionist.tools.pending_action_tools import discard_pending_action
from receptionist.tools.registration_tools import (
    confirm_new_patient_registration,
    propose_new_patient_registration,
)
from receptionist.tools.report_tools import get_report_status

ALL_TOOLS = [
    identify_patient,
    get_report_status,
    get_test_info,
    get_package_info,
    list_offers,
    suggest_tests_for_symptom,
    get_lab_info,
    get_human_handoff_number,
    check_appointment_availability,
    list_my_appointments,
    propose_new_patient_registration,
    confirm_new_patient_registration,
    propose_appointment_booking,
    confirm_appointment_booking,
    propose_appointment_change,
    confirm_appointment_change,
    propose_appointment_cancellation,
    confirm_appointment_cancellation,
    discard_pending_action,
]


class ReceptionistAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions=build_voice_instructions(), tools=ALL_TOOLS)


def build_gpt_live_model() -> GPTLiveModel:
    return GPTLiveModel(
        voice="marin",
        responses_options={
            "model": settings.reasoning_model,
            "instructions": build_reasoning_instructions(),
        },
    )
