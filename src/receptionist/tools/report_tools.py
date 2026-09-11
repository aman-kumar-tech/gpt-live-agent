from __future__ import annotations

from uuid import UUID

from livekit.agents import RunContext
from livekit.agents.llm import function_tool

from receptionist.call_state import CallState
from receptionist.db.engine import get_session_factory
from receptionist.db.repositories import reports as reports_repo


@function_tool
async def get_report_status(context: RunContext[CallState]) -> str:
    """Check whether the identified caller's lab reports are ready. Requires
    identify_patient to have been called successfully earlier in this call."""
    patient_id = context.userdata.patient_id
    if patient_id is None:
        return "The caller hasn't been identified yet. Call identify_patient first."

    session_factory = get_session_factory()
    async with session_factory() as session:
        reports = await reports_repo.list_reports_for_patient(session, UUID(patient_id))

    if not reports:
        return "No reports found for this patient."

    lines = []
    for r in reports:
        item = r.test.name if r.test else (r.package.name if r.package else "report")
        lines.append(f"{item}: {r.status}")
    return "; ".join(lines)
