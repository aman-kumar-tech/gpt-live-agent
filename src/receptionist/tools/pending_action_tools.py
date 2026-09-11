from __future__ import annotations

from langgraph.types import Command
from livekit.agents import RunContext
from livekit.agents.llm import function_tool

from receptionist.call_state import CallState


@function_tool
async def discard_pending_action(context: RunContext[CallState]) -> str:
    """Abort whatever registration/booking/reschedule/cancellation is
    currently awaiting confirmation -- e.g. if the caller says "never mind"
    or wants to change something before confirming. Nothing gets written."""
    kind = context.userdata.pending_kind
    thread_id = context.userdata.pending_thread_id
    if kind is None or thread_id is None:
        return "There's nothing pending to discard."

    graph = await context.userdata.get_graph(kind)
    await graph.ainvoke(Command(resume={"confirmed": False}), config={"configurable": {"thread_id": thread_id}})
    context.userdata.clear_pending()
    return "Okay, discarded."
