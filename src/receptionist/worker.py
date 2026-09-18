from __future__ import annotations

import logging

from dotenv import load_dotenv
from livekit.agents import Agent, AgentSession, JobContext, JobProcess, WorkerOptions, cli

# Populate real process env vars (not just our own Settings object) since the
# openai/livekit SDKs read OPENAI_API_KEY etc. straight from os.environ.
load_dotenv()

from receptionist.agent import ReceptionistAgent, build_gpt_live_model
from receptionist.auto_hangup import attach_auto_hangup
from receptionist.call_state import CallState
from receptionist.clock import lab_now
from receptionist.config import settings
from receptionist.db.engine import get_session_factory
from receptionist.db.repositories import lab_info as lab_info_repo
from receptionist.observability import attach_observability
from receptionist.tools.lab_info_tools import format_lab_info
from receptionist.winasync import ensure_selector_event_loop

ensure_selector_event_loop()

logger = logging.getLogger("receptionist.worker")


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


def _opening_greeting_instructions(known_full_name: str | None) -> str:
    """Wording for the very first generate_reply, said before the caller has
    spoken -- separate from the ongoing "don't ask again" policy in
    instructions.py (which governs the rest of the call), since this is a
    one-shot instruction for a single reply, not a standing system prompt."""
    if not known_full_name:
        return f"Greet the caller warmly, introduce yourself as {settings.agent_name}, and ask how you can help today."

    first_name = known_full_name.strip().split()[0]
    hour = lab_now().hour
    time_of_day = "morning" if hour < 12 else "afternoon" if hour < 17 else "evening"
    return (
        f'Open with a warm, brief greeting using the caller\'s first name, {first_name}, '
        f'a good-{time_of_day} greeting, and introduce yourself as {settings.agent_name} -- '
        f'e.g. "Hi {first_name}, good {time_of_day}! I\'m {settings.agent_name}." Never call '
        'yourself an AI, bot, or assistant -- introduce yourself only by name, the way a '
        "human receptionist would. Then ask how you can help today. Do not ask for their "
        "name or phone number -- you already have both."
    )


async def _fetch_lab_info_text() -> str | None:
    # Given to both prompt layers upfront (see instructions.py); None falls back to the get_lab_info tool.
    try:
        session_factory = get_session_factory()
        async with session_factory() as session:
            lab = await lab_info_repo.get_lab_info(session)
        return format_lab_info(lab) if lab else None
    except Exception:
        logger.warning("failed to fetch lab info for prompt", exc_info=True)
        return None


async def entrypoint(ctx: JobContext) -> None:
    logger.warning("job %s picked up, waiting for participant", ctx.job.id)
    # wait_for_participant() connects (if not already) and returns immediately
    # if the caller already joined, so this picks up the phone_number/full_name
    # attributes the web token server attached (server/token_server.py) without
    # a race against the caller's join.
    caller = await ctx.wait_for_participant()
    # WARNING, not INFO/DEBUG: settings.log_level defaults to WARN (see
    # config.py) to avoid backpressuring stdout, which would silently drop
    # this. One line per call is not the noise that default is guarding
    # against.
    logger.warning(
        "caller %s joined room %s with attributes=%r",
        caller.identity, ctx.room.name, caller.attributes,
    )

    call_state = CallState(
        call_session_id=ctx.room.name,
        known_full_name=caller.attributes.get("full_name") or None,
        known_phone_number=caller.attributes.get("phone_number") or None,
    )
    lab_info_text = await _fetch_lab_info_text()
    llm = build_gpt_live_model(
        known_full_name=call_state.known_full_name,
        known_phone_number=call_state.known_phone_number,
        lab_info_text=lab_info_text,
    )
    session = AgentSession(llm=llm, userdata=call_state)
    attach_observability(session, call_state.call_session_id)
    attach_auto_hangup(session, ctx)

    agent: Agent = ReceptionistAgent(
        known_full_name=call_state.known_full_name,
        known_phone_number=call_state.known_phone_number,
        lab_info_text=lab_info_text,
    )
    logger.warning("job %s starting session (GPT-Live connect)", ctx.job.id)
    await session.start(agent, room=ctx.room)
    logger.warning("job %s session started", ctx.job.id)

    session.generate_reply(instructions=_opening_greeting_instructions(call_state.known_full_name))
    logger.warning("job %s greeting handed off", ctx.job.id)


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
            # livekit-agents defaults num_idle_processes to 0 in "dev" mode
            # (vs. one per CPU core in "start"/prod mode) -- this project
            # always runs via `... worker dev` (Dockerfile, docker-compose,
            # run.py), so without this override every single call cold-spawns
            # a brand-new OS process and pays prewarm()'s import/engine-setup
            # cost inline before the caller hears anything. Keeping one
            # process warm means calls are handed to an already-prewarmed
            # process instead.
            num_idle_processes=1,
        )
    )
