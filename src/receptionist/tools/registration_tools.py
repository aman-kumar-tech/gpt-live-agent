from __future__ import annotations

import uuid

from langgraph.types import Command
from livekit.agents import RunContext
from livekit.agents.llm import function_tool

from receptionist.call_state import CallState


@function_tool
async def propose_new_patient_registration(
    context: RunContext[CallState],
    full_name: str | None = None,
    phone_number: str | None = None,
    date_of_birth: str | None = None,
    gender: str | None = None,
    email: str | None = None,
    address: str | None = None,
) -> str:
    """Propose registering a new patient. This does NOT create the patient
    yet -- read the proposed details back to the caller and only call
    confirm_new_patient_registration after they explicitly say yes.

    Args:
        full_name: The caller's name, as they give it (a single first name is fine; give last name and/or middle name too if they offer them). Never invent or default this (e.g. "User", "Guest") to fill it in. Omit this if the caller's name was already provided before the call started (you'll be told so) -- it's used automatically.
        phone_number: The caller's phone number as plain digits only (e.g. "9812340003"). Ask for just the local number, not "+91"/"+1" etc. -- but if they give a country code anyway, that's fine too, just pass along whatever digits they said (with or without it). No spaces, dashes, or spelled-out words. Convert however the caller said it (spoken digit by digit, grouped like "ninety-eight twelve", or with "double"/"triple"/"oh") into that digit string yourself first. Omit this if the caller's phone number was already provided before the call started (you'll be told so) -- it's used automatically.
        date_of_birth: ISO date (YYYY-MM-DD), if the caller gives one.
        gender: If the caller gives one.
        email: If the caller gives one.
        address: If the caller gives one.
    """
    full_name = full_name or context.userdata.known_full_name
    phone_number = phone_number or context.userdata.known_phone_number
    graph = await context.userdata.get_graph("registration")
    thread_id = str(uuid.uuid4())
    result = await graph.ainvoke(
        {
            "call_session_id": context.userdata.call_session_id,
            "full_name": full_name,
            "phone_number": phone_number,
            "date_of_birth": date_of_birth,
            "gender": gender,
            "email": email,
            "address": address,
        },
        config={"configurable": {"thread_id": thread_id}},
    )
    if "__interrupt__" in result:
        context.userdata.set_pending("registration", thread_id)
        return result["__interrupt__"][0].value["summary"] + " Should I go ahead?"
    return result.get("error") or "Could not propose registration."


@function_tool
async def confirm_new_patient_registration(context: RunContext[CallState]) -> str:
    """Confirm and finalize the pending new-patient registration. Only call
    this after the caller has explicitly said yes to the read-back."""
    if context.userdata.pending_kind != "registration" or not context.userdata.pending_thread_id:
        return "There is no pending registration to confirm."

    graph = await context.userdata.get_graph("registration")
    result = await graph.ainvoke(
        Command(resume={"confirmed": True}),
        config={"configurable": {"thread_id": context.userdata.pending_thread_id}},
    )
    context.userdata.clear_pending()

    if result.get("patient_id"):
        context.userdata.patient_id = result["patient_id"]
        return "Registration confirmed."
    return result.get("error") or "Could not complete registration."
