"""Observe-only AgentRuntime orchestration."""

from __future__ import annotations

from typing import Callable

from .contracts import (
    MemoryContext,
    MemoryContextPort,
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
        memory_context: MemoryContextPort | None = None,
        wait_seconds: float = 0.0,
    ) -> None:
        self.store = store
        self.policy = policy or WakePolicy()
        self.trace = trace
        self.clock = clock or (lambda: 0.0)
        self.memory_context = memory_context
        self.wait_seconds = max(0.0, float(wait_seconds))

    def build_context(self, event: RuntimeInput) -> MemoryContext:
        if self.memory_context is None:
            return MemoryContext()
        return self.memory_context.build_context(event)

    def observe(self, event: RuntimeInput) -> WakeDecision:
        now = event.at if event.at else self.clock()
        state = self.store.get(event.session_id)
        state.last_seen_at = now
        observed_seq = max(0, int(event.unread_seq))
        if observed_seq <= int(state.last_unread_seq):
            observed_seq = int(state.last_unread_seq) + 1
        state.last_unread_seq = observed_seq
        state.unread_count = max(
            int(event.unread_count), observed_seq - int(state.read_through_seq), 1
        )
        decision = self.policy.evaluate(event, state, now)
        state.last_action = decision.action.value
        state.last_reason = decision.reason
        if decision.action in (WakeAction.REPLY, WakeAction.PROACTIVE):
            state.last_wake_at = now
            state.ignored_streak = 0
        elif decision.action is WakeAction.IGNORE:
            state.ignored_streak += 1
        if self.wait_seconds > 0 and decision.action in (
            WakeAction.OBSERVE,
            WakeAction.WAIT,
        ):
            # Debounce new ambient traffic: every ambient event extends the
            # pending wait instead of letting an earlier deadline fire.
            state.wait_until = max(state.wait_until, now + self.wait_seconds)
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

    def quiet(self, session_id: str, seconds: float, now: float | None = None) -> SocialState:
        moment = self.clock() if now is None else now
        state = self.store.get(session_id)
        state.quiet_until = max(state.quiet_until, moment + max(0.0, float(seconds)))
        state.last_action = "quiet"
        state.last_reason = "quiet_window"
        self.store.put(state)
        return state

    def wait(self, session_id: str, seconds: float, now: float | None = None) -> SocialState:
        moment = self.clock() if now is None else now
        state = self.store.get(session_id)
        state.wait_until = max(state.wait_until, moment + max(0.0, float(seconds)))
        state.last_action = "wait"
        state.last_reason = "waiting"
        self.store.put(state)
        return state

    def mark_read(self, session_id: str, through_seq: int,
                  now: float | None = None) -> SocialState:
        state = self.store.get(session_id)
        requested = max(0, int(through_seq))
        # Never let the watermark move beyond the newest observed sequence.
        watermark = min(requested, max(0, int(state.last_unread_seq)))
        state.read_through_seq = max(state.read_through_seq, watermark)
        state.unread_count = max(
            0, int(state.last_unread_seq) - state.read_through_seq
        )
        state.last_seen_at = self.clock() if now is None else now
        self.store.put(state)
        return state

    def clear_wait(self, session_id: str, now: float | None = None) -> SocialState:
        state = self.store.get(session_id)
        state.wait_until = 0.0
        state.next_retry_at = 0.0
        state.last_seen_at = self.clock() if now is None else now
        self.store.put(state)
        return state

    def claim_dispatch(self, session_id: str, source_id: str,
                       now: float | None = None) -> int:
        """Claim one deferred dispatch before any await and count attempts."""
        moment = self.clock() if now is None else now
        state = self.store.get(session_id)
        sid = str(source_id or "")
        if state.last_dispatched_source_id != sid:
            state.dispatch_attempts = 0
        state.last_dispatched_source_id = sid
        state.dispatch_attempts += 1
        state.wait_until = 0.0
        state.next_retry_at = 0.0
        state.last_seen_at = moment
        self.store.put(state)
        return state.dispatch_attempts

    def schedule_retry(self, session_id: str, now: float, attempts: int,
                       max_attempts: int = 3, base_seconds: float = 2.0,
                       cap_seconds: float = 60.0) -> SocialState:
        """Schedule bounded retry for a failed deferred dispatch."""
        state = self.store.get(session_id)
        tries = max(1, int(attempts))
        if tries >= max(1, int(max_attempts)):
            state.wait_until = 0.0
            state.next_retry_at = 0.0
            state.last_reason = "dispatch_dead"
        else:
            delay = min(max(0.0, float(cap_seconds)),
                        max(0.1, float(base_seconds)) * (2 ** (tries - 1)))
            state.wait_until = float(now) + delay
            state.next_retry_at = state.wait_until
            state.last_reason = "dispatch_retry"
        state.last_action = "wait"
        self.store.put(state)
        return state

    def mark_delivered(self, session_id: str, now: float | None = None) -> SocialState:
        moment = self.clock() if now is None else now
        state = self.store.get(session_id)
        state.last_spoke_at = moment
        state.cooldown_until = moment + max(0.0, state.reply_cooldown_seconds)
        state.reply_count += 1
        state.unread_count = 0
        state.read_through_seq = max(state.read_through_seq, state.last_unread_seq)
        state.wait_until = 0.0
        state.next_retry_at = 0.0
        state.dispatch_attempts = 0
        self.store.put(state)
        return state
