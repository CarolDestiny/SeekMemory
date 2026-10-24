"""Due-time selection for runtime sessions.

TimingPolicy is pure. Scheduler only reads persisted state and reports which
sessions have due work; it never sends, generates or mutates state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .contracts import SessionState, SessionStateStore


@dataclass(frozen=True)
class DueRun:
    session_id: str
    reason: str
    due_at: float


class TimingPolicy:
    """Pure wait/retry timing policy over SessionState."""

    def evaluate(self, state: SessionState, now: float) -> DueRun | None:
        wait_until = float(state.wait_until or 0.0)
        retry_at = float(state.next_retry_at or 0.0)
        if retry_at > 0 and retry_at <= now:
            return DueRun(state.session_id, "retry", retry_at)
        if wait_until > 0 and wait_until <= now:
            return DueRun(state.session_id, "wait", wait_until)
        return None


class Scheduler:
    """Read-only due-session selector backed by a SessionStateStore."""

    def __init__(self, store: SessionStateStore, policy: TimingPolicy | None = None) -> None:
        self.store = store
        self.policy = policy or TimingPolicy()

    def due(self, session_ids: Iterable[str], now: float) -> tuple[DueRun, ...]:
        due: list[DueRun] = []
        for session_id in session_ids:
            try:
                state = self.store.get(str(session_id))
                item = self.policy.evaluate(state, now)
                if item is not None:
                    due.append(item)
            except Exception:  # noqa: BLE001 - one broken session must not block others
                continue
        return tuple(due)
