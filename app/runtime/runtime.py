"""Observe-only AgentRuntime orchestration."""

from __future__ import annotations

from typing import Callable

from .contracts import (
    RuntimeInput,
    SocialState,
    StateStore,
    TraceSink,
    WakeAction,
    WakeDecision,
)
from .wake import WakePolicy


class AgentRuntime:
    """Owns wake decisions and social state, independent of the host framework."""

    def __init__(
        self,
        store: StateStore,
        policy: WakePolicy | None = None,
        trace: TraceSink | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.store = store
        self.policy = policy or WakePolicy()
        self.trace = trace
        self.clock = clock or (lambda: 0.0)

    def observe(self, event: RuntimeInput) -> WakeDecision:
        now = event.at or self.clock()
        state = self.store.get(event.session_id)
        state.last_seen_at = now
        state.unread_count = max(1, int(event.unread_count))
        decision = self.policy.evaluate(event, state, now)
        state.last_action = decision.action.value
        state.last_reason = decision.reason
        if decision.action in (WakeAction.REPLY, WakeAction.PROACTIVE):
            state.last_wake_at = now
            state.ignored_streak = 0
        elif decision.action is WakeAction.IGNORE:
            state.ignored_streak += 1
        self.store.put(state)
        if self.trace is not None:
            self.trace.record(
                "runtime",
                decision.action.value,
                {
                    "reason": decision.reason,
                    "unread": state.unread_count,
                    "ignored_streak": state.ignored_streak,
                },
            )
        return decision

    def mark_delivered(self, session_id: str, now: float | None = None) -> SocialState:
        moment = self.clock() if now is None else now
        state = self.store.get(session_id)
        state.last_spoke_at = moment
        state.reply_count += 1
        state.unread_count = 0
        self.store.put(state)
        return state
