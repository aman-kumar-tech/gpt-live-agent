"""Windows-only asyncio fixup.

psycopg's async driver (used by both the app's raw DDL scripts and
langgraph-checkpoint-postgres) can't run under the default Windows
ProactorEventLoop -- it needs a selector-based loop. Call this once, before
any asyncio.run()/pytest-asyncio session, on every entrypoint that touches
Postgres asynchronously.
"""

import asyncio
import sys


def ensure_selector_event_loop() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
