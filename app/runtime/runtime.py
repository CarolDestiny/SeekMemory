"""Host-neutral attention, delivery acknowledgement and deferred orchestration."""

from __future__ import annotations

from typing import Callable

from .contracts import (
    MemoryContext,
    MemoryContextPort,
    MessageSender,
    ModelGateway,
    RunContext,
    RunDecision,
    RunResult,
    RuntimeInput,
    SessionState,
    StateStore,
    TraceSink,
    WakeAction,
)
from .deferred import DeferredDispatcher
from .deferred_store import DeferredStore, InMemoryDeferredStore
from .recorder import RunRecorder
from .wake import WakePolicy


DISPATCH_LEASE_SECONDS = 60.0


class AgentRuntime:
    """Owns attention decisions and session state, independent of the host framework."""

    def __init__(
        self,
        store: StateStore,
        policy: WakePolicy | None = None,
        trace: TraceSink | None = None,
        clock: Callable[[], float] | None = None,
        memory_context: MemoryContextPort | None = None,
        wait_seconds: float = 0.0,
        model_gateway: ModelGateway | None = None,
        message_sender: MessageSender | None = None,
        recorder: RunRecorder | None = None,
        deferred_store: DeferredStore | None = None,
    ) -> None:
        self.store = store
        self.policy = policy or WakePolicy()
        self.trace = trace
        self.clock = clock or (lambda: 0.0)
        self.memory_context = memory_context
        self.wait_seconds = max(0.0, float(wait_seconds))
        self.model_gateway = model_gateway
        self.message_sender = message_sender
        self.recorder = recorder
        self.deferred = DeferredDispatcher(self, deferred_store or InMemoryDeferredStore())

    def build_context(self, event: RuntimeInput) -> MemoryContext:
        if self.memory_context is None:
            return MemoryContext()
        return self.memory_context.build_context(event)

    def observe(self, event: RuntimeInput) -> RunDecision:
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
        if decision.action is WakeAction.REPLY:
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

    async def dispatch_deferred(
        self,
        context: RunContext,
        *,
        max_attempts: int = 3,
        base_seconds: float = 2.0,
    ) -> RunResult:
        """Generate and deliver, or recover an already delivered outbox entry."""
        return await self.deferred.dispatch(
            context, max_attempts=max_attempts, base_seconds=base_seconds,
        )

    def recover_deliveries(self, now: float | None = None) -> tuple[RunResult, ...]:
        """Retry delivered-run write-back without model calls or message sends."""
        return self.deferred.recover(self.clock() if now is None else now)

    def clear_wait(self, session_id: str, now: float | None = None) -> SessionState:
        state = self.store.get(session_id)
        state.wait_until = 0.0
        state.next_retry_at = 0.0
        state.last_seen_at = self.clock() if now is None else now
        self.store.put(state)
        return state

    def claim_dispatch(self, session_id: str, source_id: str,
                       now: float | None = None) -> int:
        """Claim before awaiting; a lease restores unfinished generation after restart."""
        moment = self.clock() if now is None else now
        state = self.store.get(session_id)
        sid = str(source_id or "")
        if state.last_dispatched_source_id != sid:
            state.dispatch_attempts = 0
        state.last_dispatched_source_id = sid
        state.dispatch_attempts += 1
        state.wait_until = 0.0
        state.next_retry_at = moment + DISPATCH_LEASE_SECONDS
        state.last_seen_at = moment
        self.store.put(state)
        if getattr(self.store, "last_error", ""):
            raise RuntimeError("dispatch_state_write_failed")
        return state.dispatch_attempts

    def schedule_retry(self, session_id: str, now: float, attempts: int,
                       max_attempts: int = 3, base_seconds: float = 2.0,
                       cap_seconds: float = 60.0,
                       read_through_seq: int | None = None) -> SessionState:
        """Schedule bounded retry for a failed deferred dispatch."""
        state = self.store.get(session_id)
        if read_through_seq is not None and state.last_unread_seq > read_through_seq:
            # A failure in an older run cannot cancel newer pending traffic.
            state.next_retry_at = 0.0
            state.dispatch_attempts = 0
            self.store.put(state)
            return state
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

    def mark_delivered(self, session_id: str, now: float | None = None,
                       *, read_through_seq: int | None = None,
                       dispatched_source_id: str | None = None) -> SessionState:
        """Acknowledge only the input captured by the delivered run."""
        moment = self.clock() if now is None else now
        state = self.store.get(session_id)
        if getattr(self.store, "last_error", ""):
            raise RuntimeError("delivery_state_read_failed")
        state.last_spoke_at = max(state.last_spoke_at, moment)
        state.cooldown_until = max(
            state.cooldown_until, moment + max(0.0, state.reply_cooldown_seconds)
        )
        watermark = state.last_unread_seq if read_through_seq is None else min(
            state.last_unread_seq, max(0, int(read_through_seq))
        )
        state.read_through_seq = max(state.read_through_seq, watermark)
        state.unread_count = max(0, state.last_unread_seq - state.read_through_seq)
        if (dispatched_source_id is not None
                and state.last_dispatched_source_id == dispatched_source_id):
            state.next_retry_at = 0.0
            state.dispatch_attempts = 0
        if state.unread_count == 0:
            state.wait_until = 0.0
            state.next_retry_at = 0.0
            state.dispatch_attempts = 0
        self.store.put(state)
        if getattr(self.store, "last_error", ""):
            raise RuntimeError("delivery_state_write_failed")
        return state
