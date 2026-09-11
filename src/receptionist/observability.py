"""Call-level observability: tokens, latency, and errors.

Wires four AgentSession events (see LiveKit's voice/events.py -- these are
the current, non-deprecated ones):

- conversation_item_added -> assistant ChatMessage.metrics gives per-turn
  latency (e2e_latency, llm_node_ttft).
- session_usage_updated -> cumulative AgentSessionUsage.model_usage gives
  token counts per model (input/output, audio/text/cached breakdown).
- error -> LLMError/STTError/TTSError/RealtimeModelError etc.
- close -> how and why the call ended.

Every event is persisted to the call_events table (one row each, raw) so any
report can be built with a SQL query later; see scripts/usage_report.py for
a ready-made one. Session callbacks fire synchronously (LiveKit's
EventEmitter does not await coroutines), so every handler here schedules its
own DB write as a background task rather than being async itself.
"""

from __future__ import annotations

import asyncio
import logging

from livekit.agents import (
    AgentSession,
    CloseEvent,
    ConversationItemAddedEvent,
    ErrorEvent,
    SessionUsageUpdatedEvent,
)

from receptionist.db.engine import get_session_factory
from receptionist.db.repositories.call_events import record_event

logger = logging.getLogger("receptionist.observability")

_LATENCY_KEYS = ("e2e_latency", "llm_node_ttft", "llm_node_tps", "tts_node_ttfb")


def _fire_and_forget(coro) -> None:
    task = asyncio.ensure_future(coro)
    task.add_done_callback(lambda t: t.exception() and logger.warning("observability write failed: %s", t.exception()))


def attach_observability(session: AgentSession, call_session_id: str) -> None:
    session_factory = get_session_factory()

    def _on_conversation_item_added(event: ConversationItemAddedEvent) -> None:
        item = event.item
        if getattr(item, "type", None) != "message" or item.role != "assistant":
            return
        latency = {k: item.metrics[k] for k in _LATENCY_KEYS if k in item.metrics}
        if not latency:
            return

        async def _write() -> None:
            async with session_factory() as db_session:
                await record_event(db_session, call_session_id, "latency", latency)

        _fire_and_forget(_write())
        if "e2e_latency" in latency:
            logger.info("call %s: agent response latency %.2fs", call_session_id, latency["e2e_latency"])

    def _on_session_usage_updated(event: SessionUsageUpdatedEvent) -> None:
        model_usage = event.usage.model_usage
        payload = {
            "models": [
                {
                    "model": u.model,
                    "provider": u.provider,
                    "input_tokens": getattr(u, "input_tokens", None),
                    "output_tokens": getattr(u, "output_tokens", None),
                    "session_duration": getattr(u, "session_duration", None),
                }
                for u in model_usage
            ],
        }

        async def _write() -> None:
            async with session_factory() as db_session:
                await record_event(db_session, call_session_id, "usage", payload)

        _fire_and_forget(_write())

    def _on_error(event: ErrorEvent) -> None:
        payload = {"error": repr(event.error), "source": repr(event.source)}
        logger.warning("call %s: error %s", call_session_id, payload["error"])

        async def _write() -> None:
            async with session_factory() as db_session:
                await record_event(db_session, call_session_id, "error", payload)

        _fire_and_forget(_write())

    def _on_close(event: CloseEvent) -> None:
        payload = {"reason": str(event.reason), "error": repr(event.error) if event.error else None}

        async def _write() -> None:
            async with session_factory() as db_session:
                await record_event(db_session, call_session_id, "close", payload)

        _fire_and_forget(_write())

    session.on("conversation_item_added", _on_conversation_item_added)
    session.on("session_usage_updated", _on_session_usage_updated)
    session.on("error", _on_error)
    session.on("close", _on_close)
