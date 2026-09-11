"""Per-call state, stored as AgentSession(userdata=...) and reached from
every tool via RunContext.userdata. Holds the caller's identified patient
(once identify_patient succeeds) and which write-capable graph -- if any --
is currently paused awaiting this caller's explicit confirmation.

pending_thread_id is intentionally the ONLY handle the confirm_*/discard_*
tools use to resume a graph -- GPT-Live never supplies it, so it can't
mix up or replay a stale proposal (see graphs/state.py)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from langgraph.graph.state import CompiledStateGraph

PendingKind = Literal["registration", "booking", "reschedule", "cancellation"]


def _graph_builders() -> dict[PendingKind, object]:
    # Imported lazily to sidestep any import-order surprises at module load time.
    from receptionist.graphs.booking_graph import build_booking_graph
    from receptionist.graphs.cancellation_graph import build_cancellation_graph
    from receptionist.graphs.registration_graph import build_registration_graph
    from receptionist.graphs.reschedule_graph import build_reschedule_graph

    return {
        "registration": build_registration_graph,
        "booking": build_booking_graph,
        "reschedule": build_reschedule_graph,
        "cancellation": build_cancellation_graph,
    }


@dataclass
class CallState:
    call_session_id: str
    patient_id: str | None = None

    pending_kind: PendingKind | None = None
    pending_thread_id: str | None = None

    _graphs: dict[PendingKind, CompiledStateGraph] = field(default_factory=dict)

    def set_pending(self, kind: PendingKind, thread_id: str) -> None:
        self.pending_kind = kind
        self.pending_thread_id = thread_id

    def clear_pending(self) -> None:
        self.pending_kind = None
        self.pending_thread_id = None

    async def get_graph(self, kind: PendingKind) -> CompiledStateGraph:
        """Lazily build (once per call) and cache each write-capable graph."""
        if kind not in self._graphs:
            self._graphs[kind] = await _graph_builders()[kind]()
        return self._graphs[kind]
