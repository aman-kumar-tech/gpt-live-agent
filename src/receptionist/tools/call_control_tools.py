from __future__ import annotations

import asyncio
import logging

from livekit.agents import RunContext, get_job_context
from livekit.agents.llm import function_tool

from receptionist.call_state import CallState

logger = logging.getLogger("receptionist.call_control")

# auto_hangup.py (agent_state-aware) is the primary mechanism for ending a
# call now -- it reliably catches the farewell whether or not the model
# calls this tool at all. This is just a secondary path for if the model
# does call it, so unlike that one, a blind fixed delay is an acceptable
# (if blunt) safety net here; kept generous since there's no way from here
# to know how long the goodbye actually takes to play out.
_END_CALL_DELAY_SECONDS = 8.0


@function_tool
async def end_call(context: RunContext[CallState]) -> str:
    """Call this once, as your very last action, right after you've said
    goodbye and the caller has confirmed they need nothing else. Ends the
    call a few seconds later, once your goodbye has finished playing."""
    ctx = get_job_context()

    async def _hang_up() -> None:
        await asyncio.sleep(_END_CALL_DELAY_SECONDS)
        ctx.delete_room()

    task = asyncio.ensure_future(_hang_up())
    task.add_done_callback(lambda t: t.exception() and logger.warning("end_call failed: %s", t.exception()))
    return "Call will end shortly."
