import uuid
from datetime import datetime, timedelta

from langgraph.types import Command
from sqlalchemy import select

from sqlalchemy import select as sa_select

from receptionist.db.engine import get_session_factory
from receptionist.db.models import Appointment
from receptionist.db.models import Test as TestModel
from receptionist.db.repositories.appointments import create_appointment
from receptionist.db.repositories.patients import find_patients_by_phone
from receptionist.graphs.cancellation_graph import build_cancellation_graph
from receptionist.graphs.reschedule_graph import build_reschedule_graph

SEEDED_PATIENT_PHONE = "+919812340002"  # Amit Verma, seeded from data.json by db/seed.py


async def _make_fresh_booked_appointment() -> tuple[str, str]:
    session_factory = get_session_factory()
    async with session_factory() as session:
        patients = await find_patients_by_phone(session, SEEDED_PATIENT_PHONE)
        patient = patients[0]
        any_test = (await session.execute(sa_select(TestModel).limit(1))).scalar_one()
        scheduled_at = (datetime.now() + timedelta(days=300 + uuid.uuid4().int % 1000)).replace(second=0, microsecond=0)
        appointment = await create_appointment(
            session, patient_id=patient.id, appointment_type="lab_visit", scheduled_at=scheduled_at, test_ids=[any_test.id]
        )
        await session.commit()
        return appointment.reference_code, str(patient.id)


async def test_reschedule_requires_confirmation_before_writing():
    reference_code, patient_id = await _make_fresh_booked_appointment()
    graph = await build_reschedule_graph()
    new_dt = (datetime.now() + timedelta(days=300 + uuid.uuid4().int % 1000)).replace(second=0, microsecond=0)
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    proposed = await graph.ainvoke(
        {
            "call_session_id": f"test-call-resched-1-{uuid.uuid4()}",
            "patient_id": patient_id,
            "reference_code": reference_code,
            "new_scheduled_at": new_dt.isoformat(),
        },
        config=config,
    )
    assert "__interrupt__" in proposed

    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(select(Appointment).where(Appointment.reference_code == reference_code))
        original = result.scalar_one()
        assert original.status == "booked", "old appointment untouched before confirmation"

    confirmed = await graph.ainvoke(Command(resume={"confirmed": True}), config=config)
    assert confirmed["new_reference_code"]
    assert confirmed["new_reference_code"] != reference_code

    async with session_factory() as session:
        result = await session.execute(select(Appointment).where(Appointment.reference_code == reference_code))
        assert result.scalar_one().status == "rescheduled"

        result = await session.execute(
            select(Appointment).where(Appointment.reference_code == confirmed["new_reference_code"])
        )
        new_appointment = result.scalar_one()
        assert new_appointment.status == "booked"
        assert new_appointment.scheduled_at == new_dt


async def test_reschedule_rejects_wrong_patient():
    reference_code, _ = await _make_fresh_booked_appointment()
    graph = await build_reschedule_graph()
    new_dt = datetime.now() + timedelta(days=32)
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    result = await graph.ainvoke(
        {
            "call_session_id": "test-call-resched-2",
            "patient_id": str(uuid.uuid4()),  # not the appointment's owner
            "reference_code": reference_code,
            "new_scheduled_at": new_dt.isoformat(),
        },
        config=config,
    )
    assert "__interrupt__" not in result
    assert "doesn't belong" in result["error"]


async def test_cancellation_requires_confirmation_before_writing():
    reference_code, patient_id = await _make_fresh_booked_appointment()
    graph = await build_cancellation_graph()
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    proposed = await graph.ainvoke(
        {"call_session_id": "test-call-cancel-1", "patient_id": patient_id, "reference_code": reference_code},
        config=config,
    )
    assert "__interrupt__" in proposed

    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(select(Appointment).where(Appointment.reference_code == reference_code))
        assert result.scalar_one().status == "booked"

    confirmed = await graph.ainvoke(Command(resume={"confirmed": True}), config=config)
    assert confirmed["cancelled"] is True

    async with session_factory() as session:
        result = await session.execute(select(Appointment).where(Appointment.reference_code == reference_code))
        assert result.scalar_one().status == "cancelled"


async def test_cancellation_discard_leaves_appointment_booked():
    reference_code, patient_id = await _make_fresh_booked_appointment()
    graph = await build_cancellation_graph()
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    await graph.ainvoke(
        {"call_session_id": "test-call-cancel-2", "patient_id": patient_id, "reference_code": reference_code},
        config=config,
    )
    await graph.ainvoke(Command(resume={"confirmed": False}), config=config)

    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(select(Appointment).where(Appointment.reference_code == reference_code))
        assert result.scalar_one().status == "booked"
