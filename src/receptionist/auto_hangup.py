"""Backstop for ending a call.

Observed live, repeatedly: gpt-4o-mini reliably says a natural goodbye
("Take care." / "Bye.") but does not reliably follow through on calling the
end_call tool afterward -- the call just stays open, listening, until the
caller manually disconnects. Rather than depend on the model remembering a
tool call as a deliberate last step, detect the farewell in its own spoken
words and end the room shortly after.

Three things this got wrong across earlier passes, all fixed here:

1. Driven entirely by the agent's own messages, not the caller's: an
   earlier version cancelled the pending hangup on any caller reply at all,
   including their own "Bye" or "Okay" -- exactly the acknowledgments that
   should let the goodbye proceed, not cancel it. The caller's words never
   directly decide this, only what the agent chooses to say back.

2. Timed from when the agent actually stops talking, not from when the
   farewell text appears: a fixed delay from conversation_item_added alone
   cut the call off mid-sentence when the farewell turn was longer than
   expected (e.g. spelling out a confirmation code after "booking confirmed"
   -- observed live cutting off mid reference-code).

3. Don't assume which of conversation_item_added / agent_state_changed
   fires first for the same turn to decide "has playout finished yet". A
   next-attempt version gated the hangup on an old_state=="speaking"
   transition happening AFTER the farewell text arrived -- but reading
   livekit-agents' realtime generation path (agent_activity.py) shows the
   state leaving "speaking" is updated BEFORE the per-message
   conversation_item_added calls for that same turn, which would make that
   version's check always look at a stale (previous-turn) farewell flag and
   silently never fire. Rather than trust that reading over the live
   mid-sentence-cutoff behavior that motivated adding the state check in the
   first place (they disagree, and this plugin's actual code path wasn't
   fully traced either way), this checks session.agent_state directly --
   synchronous, doesn't depend on which event arrives first -- and only
   falls back to waiting for the next transition if speech is still
   genuinely in progress at that moment.

4. Matching the farewell phrase anywhere in the turn's text, not just at its
   end: observed live cutting off a registration/booking mid-flow, because
   gpt-4o-mini routinely says "I'll take care of registering you" / "let me
   take care of that booking" as filler -- ordinary "I'll handle it"
   phrasing, not a goodbye, but the same words. Anchoring the match to the
   end of the turn (only trailing whitespace/punctuation allowed after it)
   keeps "take care" etc. as sign-offs while no longer matching that filler,
   since a real goodbye is always the last thing said in the turn.
"""

from __future__ import annotations

import asyncio
import logging
import re

from livekit.agents import AgentSession, ConversationItemAddedEvent, JobContext
from livekit.agents.voice.events import AgentStateChangedEvent

logger = logging.getLogger("receptionist.auto_hangup")

_FAREWELL_RE = re.compile(
    r"\b(take care|goodbye|good bye|bye|have a (great|good|wonderful) day)\b[\s.!?]*\Z",
    re.IGNORECASE,
)
_GRACE_SECONDS = 3.0


def attach_auto_hangup(session: AgentSession, ctx: JobContext) -> None:
    pending_hangup: asyncio.Task | None = None
    last_was_farewell = False

    def _cancel_pending() -> None:
        nonlocal pending_hangup
        if pending_hangup is not None and not pending_hangup.done():
            pending_hangup.cancel()
        pending_hangup = None

    def _arm() -> None:
        nonlocal pending_hangup

        async def _hang_up() -> None:
            await asyncio.sleep(_GRACE_SECONDS)
            ctx.delete_room()

        _cancel_pending()
        pending_hangup = asyncio.ensure_future(_hang_up())
        pending_hangup.add_done_callback(
            lambda t: (not t.cancelled()) and t.exception() and logger.warning("auto hangup failed: %s", t.exception())
        )

    def _on_conversation_item_added(event: ConversationItemAddedEvent) -> None:
        nonlocal last_was_farewell
        item = event.item
        if getattr(item, "type", None) != "message" or item.role != "assistant":
            return

        last_was_farewell = bool(_FAREWELL_RE.search(item.text_content or ""))
        if not last_was_farewell:
            _cancel_pending()  # agent is engaged on something else -- don't hang up
            return

        if session.agent_state != "speaking":
            _arm()  # playout for this turn has already finished
        # else: still speaking -- _on_agent_state_changed below arms it once done

    def _on_agent_state_changed(event: AgentStateChangedEvent) -> None:
        # catches the case where the farewell text arrived while still
        # speaking (item-added fired before the state transition) -- _arm()
        # is idempotent, so if item-added already armed it via the branch
        # above, this is a harmless no-op re-arm, not a double-hangup
        if last_was_farewell and event.old_state == "speaking" and event.new_state != "speaking":
            _arm()

    session.on("conversation_item_added", _on_conversation_item_added)
    session.on("agent_state_changed", _on_agent_state_changed)
