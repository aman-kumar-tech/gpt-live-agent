"""One-time DDL for the LangGraph Postgres checkpointer's own tables."""

import asyncio

from receptionist.graphs.checkpointer import close_checkpointer, setup_checkpointer_tables
from receptionist.winasync import ensure_selector_event_loop

ensure_selector_event_loop()


async def main() -> None:
    await setup_checkpointer_tables()
    await close_checkpointer()
    print("Checkpointer tables ready.")


if __name__ == "__main__":
    asyncio.run(main())
