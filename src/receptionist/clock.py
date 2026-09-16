"""Lab-local wall-clock time.

The lab is in Pune, India (Asia/Kolkata, UTC+5:30, no DST), but this
process's own system clock is UTC (standard for these Docker images) --
so a bare datetime.now() is silently 5.5 hours behind the lab's actual
local time. Every timestamp in this app that represents a caller-facing
moment (an appointment's scheduled_at, "today" for an active offer, the
"right now" told to the LLM) is a naive datetime and implicitly lab-local,
not UTC -- so any business logic that computes "now"/"today" to compare
against one of those must go through here, not datetime.now()/date.today()
directly, or it silently treats already-past times as still bookable.

Exception: purely-internal bookkeeping that's self-consistent against
Postgres's own now() (pending_actions.expires_at, set server-side via SQL
now() + interval) should keep using plain datetime.now() -- it compares
against another UTC value, never against a caller-facing lab-local one.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

LAB_TZ = ZoneInfo("Asia/Kolkata")


def lab_now() -> datetime:
    """Current wall-clock time in the lab's timezone, as a naive datetime --
    matching how scheduled_at/created_at are stored (see module docstring)."""
    return datetime.now(LAB_TZ).replace(tzinfo=None)


def lab_today() -> date:
    return lab_now().date()
