from __future__ import annotations

from dotenv import load_dotenv
from livekit.agents import Agent, AgentSession, JobContext, JobProcess, WorkerOptions, cli

# Populate real process env vars (not just our own Settings object) since the
# openai/livekit SDKs read OPENAI_API_KEY etc. straight from os.environ.
load_dotenv()

from receptionist.agent import ReceptionistAgent, build_gpt_live_model
from receptionist.call_state import CallState
from receptionist.config import settings
from receptionist.observability import attach_observability
from receptionist.winasync import ensure_selector_event_loop

ensure_selector_event_loop()


def prewarm(proc: JobProcess) -> None:
    # Engine/checkpointer are process-wide lazy singletons (see db/engine.py
    # and graphs/checkpointer.py) -- nothing to eagerly build here yet, but
    # this is the hook if that changes.
    proc.userdata["ready"] = True


async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()

    call_state = CallState(call_session_id=ctx.room.name)
    session = AgentSession(llm=build_gpt_live_model(), userdata=call_state)
    attach_observability(session, call_state.call_session_id)

    agent: Agent = ReceptionistAgent()
    await session.start(agent, room=ctx.room)


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
