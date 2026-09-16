"""Call-level observability: tokens, errors, and tool calls.

Wires four AgentSession events (see LiveKit's voice/events.py -- these are
the current, non-deprecated ones):

- session_usage_updated -> cumulative AgentSessionUsage.model_usage gives
  token counts per model (input/output, audio/text/cached breakdown).
- error -> LLMError/STTError/TTSError/RealtimeModelError etc.
- close -> how and why the call ended.
- function_tools_executed -> every tool call this turn, with its arguments
  and result/error. Without this there is no record anywhere of what a
  caller actually asked for or what a tool returned (an exception inside a
  tool, like the identify_patient crash this was added after, never reaches
  the `error` listener above -- that one only fires for session-level
  STT/LLM/TTS/etc. errors) -- diagnosing a bad call meant reading raw
  DEBUG-level docker logs, if they hadn't already rotated away.

conversation_item_added's per-turn latency fields (e2e_latency, llm_node_ttft
etc. on assistant ChatMessage.metrics) are STT->LLM->TTS pipeline metrics --
GPT-Live is a speech-to-speech realtime model, so they're never populated,
and there's deliberately no listener for that event here. This still does
NOT log conversation text (what the caller/agent actually said) -- only
which tools were called, with what arguments, and what they returned.

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
    ErrorEvent,
    FunctionToolsExecutedEvent,
    SessionUsageUpdatedEvent,
)

from receptionist.db.engine import get_session_factory
from receptionist.db.repositories.call_events import record_event

logger = logging.getLogger("receptionist.observability")


def _fire_and_forget(coro) -> None:
    task = asyncio.ensure_future(coro)
    task.add_done_callback(lambda t: t.exception() and logger.warning("observability write failed: %s", t.exception()))


def attach_observability(session: AgentSession, call_session_id: str) -> None:
    session_factory = get_session_factory()

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

    def _on_function_tools_executed(event: FunctionToolsExecutedEvent) -> None:
        for call, output in event.zipped():
            payload = {
                "name": call.name,
                "arguments": call.arguments,
                "output": output.output,
                "is_error": output.is_error,
            }
            if output.is_error:
                logger.warning("call %s: tool %s failed: %s", call_session_id, call.name, output.output)

            async def _write(payload=payload) -> None:
                async with session_factory() as db_session:
                    await record_event(db_session, call_session_id, "tool_call", payload)

            _fire_and_forget(_write())

    session.on("session_usage_updated", _on_session_usage_updated)
    session.on("error", _on_error)
    session.on("close", _on_close)
    session.on("function_tools_executed", _on_function_tools_executed)
