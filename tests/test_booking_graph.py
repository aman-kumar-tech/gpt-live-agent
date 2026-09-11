import uuid
from datetime import datetime, timedelta

from langgraph.types import Command
from sqlalchemy import select

from receptionist.db.engine import get_session_factory
from receptionist.db.models import Appointment
from receptionist.db.models import Test as TestModel
from receptionist.db.repositories.patients import find_patients_by_phone
from receptionist.graphs.booking_graph import build_booking_graph

SEEDED_PATIENT_PHONE = "+919812340002"  # Amit Verma, seeded from data.json by db/seed.py


async def _get_seeded_patient_id() -> str:
    session_factory = get_session_factory()
    async with session_factory() as session:
        patients = await find_patients_by_phone(session, SEEDED_PATIENT_PHONE)
        assert patients, "run db/seed.py before running these tests"
        return str(patients[0].id)


async def test_booking_requires_confirmation_before_writing():
    graph = await build_booking_graph()
    patient_id = await _get_seeded_patient_id()
    scheduled_at = (datetime.now() + timedelta(days=200 + uuid.uuid4().int % 1000)).replace(second=0, microsecond=0)
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    proposed = await graph.ainvoke(
        {
            "call_session_id": f"test-call-book-1-{uuid.uuid4()}",
            "patient_id": patient_id,
            "appointment_type": "lab_visit",
            "scheduled_at": scheduled_at.isoformat(),
            "test_names": ["CBC"],  # matches T004 (Complete Blood Count) via alias
        },
        config=config,
    )
    assert "__interrupt__" in proposed
    assert "₹350.00" in proposed["__interrupt__"][0].value["summary"]

    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(select(Appointment).where(Appointment.scheduled_at == scheduled_at))
        assert result.scalars().all() == [], "no appointment row before confirmation"

    confirmed = await graph.ainvoke(Command(resume={"confirmed": True}), config=config)
    assert confirmed["appointment_id"] is not None
    assert confirmed["reference_code"]

    async with session_factory() as session:
        result = await session.execute(select(Appointment).where(Appointment.scheduled_at == scheduled_at))
        appointment = result.scalar_one()
        assert appointment.status == "booked"
        assert appointment.type == "lab_visit"


async def test_booking_discard_writes_nothing():
    graph = await build_booking_graph()
    patient_id = await _get_seeded_patient_id()
    scheduled_at = (datetime.now() + timedelta(days=200 + uuid.uuid4().int % 1000)).replace(second=0, microsecond=0)
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    await graph.ainvoke(
        {
            "call_session_id": f"test-call-book-2-{uuid.uuid4()}",
            "patient_id": patient_id,
            "appointment_type": "lab_visit",
            "scheduled_at": scheduled_at.isoformat(),
            "test_names": ["CBC"],
        },
        config=config,
    )

    aborted = await graph.ainvoke(Command(resume={"confirmed": False}), config=config)
    assert aborted.get("appointment_id") is None

    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(select(Appointment).where(Appointment.scheduled_at == scheduled_at))
        assert result.scalars().all() == []


async def test_booking_rejects_home_collection_for_ineligible_test():
    # data.json's catalog happens to have every test home-collection-eligible,
    # so this exercises the rejection path with a throwaway ineligible row
    # rather than relying on that being true of the seeded catalog forever.
    session_factory = get_session_factory()
    async with session_factory() as session:
        ineligible = TestModel(
            code=f"TEST_INELIGIBLE_{uuid.uuid4().hex[:6]}",
            name="Lab-Only Imaging Test",
            price=999,
            home_collection_available=False,
        )
        session.add(ineligible)
        await session.commit()
        test_name = ineligible.name

    graph = await build_booking_graph()
    patient_id = await _get_seeded_patient_id()
    scheduled_at = datetime.now() + timedelta(days=250)
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    result = await graph.ainvoke(
        {
            "call_session_id": f"test-call-book-3-{uuid.uuid4()}",
            "patient_id": patient_id,
            "appointment_type": "home_collection",
            "scheduled_at": scheduled_at.isoformat(),
            "test_names": [test_name],
            "address": "123 Test Street",
        },
        config=config,
    )
    assert "__interrupt__" not in result
    assert "home collection isn't available" in result["error"]


async def test_booking_rejects_scheduling_within_lead_time():
    graph = await build_booking_graph()
    patient_id = await _get_seeded_patient_id()
    scheduled_at = datetime.now() + timedelta(minutes=5)
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    result = await graph.ainvoke(
        {
            "call_session_id": f"test-call-book-4-{uuid.uuid4()}",
            "patient_id": patient_id,
            "appointment_type": "lab_visit",
            "scheduled_at": scheduled_at.isoformat(),
            "test_names": ["CBC"],
        },
        config=config,
    )
    assert "__interrupt__" not in result
    assert "hours" in result["error"]
