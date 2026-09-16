from __future__ import annotations

from dotenv import load_dotenv
from livekit.agents import Agent, AgentSession, JobContext, JobProcess, WorkerOptions, cli

# Populate real process env vars (not just our own Settings object) since the
# openai/livekit SDKs read OPENAI_API_KEY etc. straight from os.environ.
load_dotenv()

from receptionist.agent import ReceptionistAgent, build_gpt_live_model
from receptionist.auto_hangup import attach_auto_hangup
from receptionist.call_state import CallState
from receptionist.config import settings
from receptionist.observability import attach_observability
from receptionist.winasync import ensure_selector_event_loop

ensure_selector_event_loop()


def prewarm(proc: JobProcess) -> None:
    # Importing asyncpg/psycopg and the graph modules is expensive (hundreds
    # of ms) and was happening lazily on the first DB call / first propose_*
    # tool call of a live call, synchronously blocking the agent's event loop
    # mid-session (seen as livekit.agents "event loop blocked" warnings, up to
    # ~540ms importing receptionist.db.repositories.pending_actions from
    # inside a tool_exec call). Pay that cost here instead, before any call
    # is dispatched to this process.
    from receptionist.db.engine import get_engine
    from receptionist.graphs.booking_graph import build_booking_graph  # noqa: F401
    from receptionist.graphs.cancellation_graph import build_cancellation_graph  # noqa: F401
    from receptionist.graphs.registration_graph import build_registration_graph  # noqa: F401
    from receptionist.graphs.reschedule_graph import build_reschedule_graph  # noqa: F401

    get_engine()
    proc.userdata["ready"] = True


async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()

    call_state = CallState(call_session_id=ctx.room.name)
    session = AgentSession(llm=build_gpt_live_model(), userdata=call_state)
    attach_observability(session, call_state.call_session_id)
    attach_auto_hangup(session, ctx)

    agent: Agent = ReceptionistAgent()
    await session.start(agent, room=ctx.room)
    session.generate_reply(instructions="Greet the caller warmly and ask how you can help today.")


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
            ws_url=settings.livekit_url,
            api_key=settings.livekit_api_key,
            api_secret=settings.livekit_api_secret,
            # "dev" mode defaults to DEBUG otherwise -- see config.py's log_level comment.
            log_level=settings.log_level,
        )
    )
