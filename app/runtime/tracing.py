"""Per-event run correlation: observers never change agent behavior."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4

try:
    from ...core.trace import recall_data
except ImportError:
    from core.trace import recall_data


class TraceWriter(Protocol):
    def append(self, row: dict) -> None: ...


@dataclass
class RunState:
    id: str = field(default_factory=lambda: uuid4().hex)
    sequence: int = 0
    request_index: int = 0
    done: bool = False
    delivered: bool = False
    requested_at: float | None = None
    tools: dict[int, tuple[float | None, int]] = field(default_factory=dict)


class RunTracer:
    def __init__(self, store: TraceWriter, *, clock=time.time) -> None:
        self.store = store
        self.clock = clock

    def _state(self, event) -> RunState:
        state = event.get_extra("_seekmemory_run_trace", None)
        if not isinstance(state, RunState):
            state = RunState()
            event.set_extra("_seekmemory_run_trace", state)
        return state

    def _record(self, state: RunState, name: str, status: str = "unknown", **values) -> None:
        state.sequence += 1
        self.store.append({"run_id": state.id, "sequence": state.sequence,
            "request_index": state.request_index,
            "at": datetime.fromtimestamp(self.clock(), timezone.utc).isoformat(),
            "event": name, "status": status, **values})

    def run_id(self, event) -> str:
        try:
            return self._state(event).id
        except Exception:
            return ""

    def begin(self, event) -> None:
        try:
            state = self._state(event)
            if state.done:
                state = RunState()
                event.set_extra("_seekmemory_run_trace", state)
            self._record(state, "agent_begin", "running")
        except Exception:
            pass

    def request(self, event, info: dict | None, status: str = "ok") -> None:
        try:
            state = self._state(event)
            if state.done:
                state = RunState()
                event.set_extra("_seekmemory_run_trace", state)
            state.request_index += 1
            state.requested_at = self.clock()
            self._record(state, "llm_request", status,
                         recall=recall_data(info) if info is not None else None)
        except Exception:
            pass

    def response(self, event, status: str) -> None:
        try:
            state = self._state(event)
            elapsed = None if state.requested_at is None else max(0, (self.clock() - state.requested_at) * 1000)
            self._record(state, "llm_response", status, duration_ms=elapsed)
        except Exception:
            pass

    def done(self, event, status: str) -> None:
        try:
            state = self._state(event)
            if not state.done:
                self._record(state, "agent_done", status)
                state.done = True
                state.tools.clear()
        except Exception:
            pass

    def delivered(self, event) -> None:
        try:
            state = event.get_extra("_seekmemory_run_trace", None)
            if isinstance(state, RunState) and not state.delivered:
                self._record(state, "message_sent", "ok")
                state.delivered = True
        except Exception:
            pass

    def tool_begin(self, event, tool) -> None:
        try:
            state = self._state(event)
            name = str(getattr(tool, "name", ""))
            previous = state.tools.get(id(tool))
            # The host supplies no call id: overlapping calls cannot be timed honestly.
            state.tools[id(tool)] = (self.clock(), 1) if previous is None else (None, previous[1] + 1)
            self._record(state, "tool_call", "running", tool=name)
        except Exception:
            pass

    def tool_end(self, event, tool) -> None:
        try:
            state = self._state(event)
            start = state.tools.pop(id(tool), None)
            if start is not None and start[1] > 1:
                state.tools[id(tool)] = (None, start[1] - 1)
            duration = None if start is None or start[0] is None else max(0, (self.clock() - start[0]) * 1000)
            self._record(state, "tool_result", "unknown",
                         tool=str(getattr(tool, "name", "")), duration_ms=duration)
        except Exception:
            pass
