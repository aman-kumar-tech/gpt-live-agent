import pytest

from receptionist.winasync import ensure_selector_event_loop

ensure_selector_event_loop()


@pytest.fixture(autouse=True)
async def _fresh_engine_and_checkpointer_per_test():
    """pytest-asyncio gives each test function its own event loop, but our
    SQLAlchemy engine and LangGraph checkpointer are process-wide singletons
    (by design -- the real worker is one long-running process/loop). Reset
    both before and after every test so pooled connections are never reused
    across event loops."""
    from receptionist.db.engine import dispose_engine
    from receptionist.graphs.checkpointer import close_checkpointer

    await dispose_engine()
    await close_checkpointer()
    yield
    await dispose_engine()
    await close_checkpointer()
