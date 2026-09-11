"""A single process-wide AsyncPostgresSaver, opened once (worker prewarm or
test setup) and reused across every graph invocation for the life of the
process -- see plan step 7 / risk #4 (state must survive across two separate
GPT-Live tool calls with a live voice turn in between)."""

from __future__ import annotations

from contextlib import AsyncExitStack

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from receptionist.config import settings

_stack: AsyncExitStack | None = None
_saver: AsyncPostgresSaver | None = None


async def get_checkpointer() -> AsyncPostgresSaver:
    global _stack, _saver
    if _saver is None:
        _stack = AsyncExitStack()
        _saver = await _stack.enter_async_context(
            AsyncPostgresSaver.from_conn_string(settings.checkpointer_database_url)
        )
    return _saver


async def close_checkpointer() -> None:
    global _stack, _saver
    if _stack is not None:
        await _stack.aclose()
    _stack = None
    _saver = None


async def setup_checkpointer_tables() -> None:
    """One-time DDL for the checkpointer's own tables. Idempotent."""
    saver = await get_checkpointer()
    await saver.setup()
