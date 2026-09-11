import uuid

from langgraph.types import Command
from sqlalchemy import select

from receptionist.db.engine import get_session_factory
from receptionist.db.models import PendingAction
from receptionist.db.repositories.patients import find_patients_by_phone
from receptionist.graphs.registration_graph import build_registration_graph


async def test_registration_requires_confirmation_before_writing():
    graph = await build_registration_graph()
    phone = f"+1555{uuid.uuid4().int % 10_000_000:07d}"
    call_session_id = f"test-call-reg-1-{uuid.uuid4()}"
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    proposed = await graph.ainvoke(
        {"call_session_id": call_session_id, "full_name": "Test Newperson", "phone_number": phone},
        config=config,
    )
    assert "__interrupt__" in proposed, "graph should pause for confirmation, not commit immediately"

    session_factory = get_session_factory()
    async with session_factory() as session:
        assert await find_patients_by_phone(session, phone) == [], "no patient row before confirmation"
        result = await session.execute(
            select(PendingAction).where(PendingAction.call_session_id == call_session_id)
        )
        pending = result.scalar_one()
        assert pending.status == "proposed"

    confirmed = await graph.ainvoke(Command(resume={"confirmed": True}), config=config)
    assert confirmed["patient_id"] is not None

    async with session_factory() as session:
        patients = await find_patients_by_phone(session, phone)
        assert len(patients) == 1
        assert patients[0].full_name == "Test Newperson"

        result = await session.execute(
            select(PendingAction).where(PendingAction.call_session_id == call_session_id)
        )
        assert result.scalar_one().status == "confirmed"


async def test_registration_discard_writes_nothing():
    graph = await build_registration_graph()
    phone = f"+1555{uuid.uuid4().int % 10_000_000:07d}"
    call_session_id = f"test-call-reg-2-{uuid.uuid4()}"
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    await graph.ainvoke(
        {"call_session_id": call_session_id, "full_name": "Test Neverperson", "phone_number": phone},
        config=config,
    )

    aborted = await graph.ainvoke(Command(resume={"confirmed": False}), config=config)
    assert aborted.get("patient_id") is None

    session_factory = get_session_factory()
    async with session_factory() as session:
        assert await find_patients_by_phone(session, phone) == []
        result = await session.execute(
            select(PendingAction).where(PendingAction.call_session_id == call_session_id)
        )
        assert result.scalar_one().status == "rejected"


async def test_registration_rejects_duplicate_without_pausing():
    graph = await build_registration_graph()
    phone = f"+1555{uuid.uuid4().int % 10_000_000:07d}"
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    await graph.ainvoke(
        {"call_session_id": f"test-call-reg-3-{uuid.uuid4()}", "full_name": "Dup Person", "phone_number": phone},
        config=config,
    )
    await graph.ainvoke(Command(resume={"confirmed": True}), config=config)

    second_config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    second = await graph.ainvoke(
        {"call_session_id": f"test-call-reg-3b-{uuid.uuid4()}", "full_name": "Dup Person", "phone_number": phone},
        config=second_config,
    )
    assert "__interrupt__" not in second
    assert second.get("error")


async def test_registration_rejects_invalid_phone_number_without_pausing():
    graph = await build_registration_graph()
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    result = await graph.ainvoke(
        {
            "call_session_id": f"test-call-reg-4-{uuid.uuid4()}",
            "full_name": "Bad Phone",
            "phone_number": "not-a-number",
        },
        config=config,
    )
    assert "__interrupt__" not in result, "invalid input should reject immediately, not stage for confirmation"
    assert result.get("error")


async def test_registration_rejects_unreasonable_date_of_birth():
    graph = await build_registration_graph()
    phone = f"+1555{uuid.uuid4().int % 10_000_000:07d}"
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    result = await graph.ainvoke(
        {
            "call_session_id": f"test-call-reg-5-{uuid.uuid4()}",
            "full_name": "Too Old",
            "phone_number": phone,
            "date_of_birth": "1850-01-01",
        },
        config=config,
    )
    assert "__interrupt__" not in result
    assert result.get("error")

    session_factory = get_session_factory()
    async with session_factory() as session:
        assert await find_patients_by_phone(session, phone) == []
