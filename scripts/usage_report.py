"""Prints a summary of tokens, latency, and errors from the
call_events table. Run after some calls have happened:

    PYTHONPATH=src python scripts/usage_report.py [--since-hours 24]
"""

import argparse
import asyncio
from collections import Counter
from datetime import datetime, timedelta

from receptionist.db.engine import dispose_engine, get_session_factory
from receptionist.db.repositories.call_events import list_events
from receptionist.winasync import ensure_selector_event_loop

ensure_selector_event_loop()


async def main(since_hours: float | None) -> None:
    since = datetime.now() - timedelta(hours=since_hours) if since_hours else None

    session_factory = get_session_factory()
    async with session_factory() as session:
        usage_events = await list_events(session, event_type="usage", since=since)
        latency_events = await list_events(session, event_type="latency", since=since)
        error_events = await list_events(session, event_type="error", since=since)
        close_events = await list_events(session, event_type="close", since=since)

    calls = {e.call_session_id for e in usage_events + latency_events + error_events + close_events}
    print(f"Calls: {len(calls)}")

    token_totals: Counter[str] = Counter()
    for event in usage_events:
        for model in event.payload.get("models", []):
            key = model.get("model") or "unknown"
            token_totals[f"{key} input"] += model.get("input_tokens") or 0
            token_totals[f"{key} output"] += model.get("output_tokens") or 0
    print("Tokens by model:")
    for key, count in sorted(token_totals.items()):
        print(f"  {key}: {count}")

    e2e_latencies = [e.payload.get("e2e_latency") for e in latency_events if "e2e_latency" in e.payload]
    if e2e_latencies:
        e2e_latencies.sort()
        avg = sum(e2e_latencies) / len(e2e_latencies)
        p95 = e2e_latencies[int(len(e2e_latencies) * 0.95) - 1]
        print(f"Agent response latency (e2e): avg {avg:.2f}s, p95 {p95:.2f}s, n={len(e2e_latencies)}")
    else:
        print("Agent response latency: no data yet")

    print(f"Errors: {len(error_events)}")
    for event in error_events[:10]:
        print(f"  [{event.created_at}] {event.payload.get('error')}")

    close_reasons = Counter(e.payload.get("reason") for e in close_events)
    if close_reasons:
        print("Call close reasons:", dict(close_reasons))

    await dispose_engine()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--since-hours", type=float, default=None, help="Only include events from the last N hours")
    args = parser.parse_args()
    asyncio.run(main(args.since_hours))
