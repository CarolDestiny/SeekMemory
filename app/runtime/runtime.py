"""Observe-only AgentRuntime orchestration."""

from __future__ import annotations

import asyncio
import datetime
from dataclasses import replace
from typing import Callable

from .contracts import (
    MemoryContext,
    MemoryContextPort,
    MemoryContextRequest,
    MessageSender,
    ModelGateway,
    RunContext,
    RunDecision,
    RunResult,
    RuntimeInput,
    SessionState,
    UserRunReceipt,
    SessionStateStore,
    TraceSink,
    WakeAction,
)
from .recorder import RecordedReply, RunRecorder
from .wake import WakePolicy


class AgentRuntime:
    """Owns attention decisions and session state, independent of the host framework."""

    def __init__(
        self,
        store: SessionStateStore,
        policy: WakePolicy | None = None,
        trace: TraceSink | None = None,
        clock: Callable[[], float] | None = None,
        memory_context: MemoryContextPort | None = None,
        wait_seconds: float = 0.0,
        model_gateway: ModelGateway | None = None,
        message_sender: MessageSender | None = None,
        recorder: RunRecorder | None = None,
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

    def build_context(
        self,
        event: RuntimeInput,
        *,
        now: float | None = None,
        reason: str = "inbound",
    ) -> MemoryContext:
        if self.memory_context is None:
            return MemoryContext()
        moment = self.clock() if now is None else float(now)
        request = MemoryContextRequest(
            session_id=event.session_id,
            query=event.text,
            speaker_id=event.speaker_id,
            private=event.private,
            event_time=event.event_time,
            received_at=event.received_at,
            now=moment,
            reason=reason,
        )
        return self.memory_context.build_context(request)

    def _save(self, state: SessionState) -> None:
        state.revision = max(0, int(state.revision or 0)) + 1
        self.store.put(state)

    def observe(
        self, event: RuntimeInput, *, now: float | None = None
    ) -> RunDecision:
        moment = self.clock() if now is None else float(now)
        state = self.store.get(event.session_id)
        event_time = float(event.event_time or 0.0)
        if event_time > 0 and state.last_event_at > event_time:
            if self.trace is not None:
                self.trace.record(
                    "runtime",
                    "stale_event",
                    {
                        "event_time": event_time,
                        "last_event_at": state.last_event_at,
                    },
                )
            return RunDecision(WakeAction.IGNORE, "stale_event")
        if event_time > 0:
            state.last_event_at = max(state.last_event_at, event_time)
        state.last_seen_at = moment
        observed_seq = max(0, int(event.unread_seq))
        if observed_seq <= int(state.last_unread_seq):
            observed_seq = int(state.last_unread_seq) + 1
        state.last_unread_seq = observed_seq
        state.unread_count = max(
            int(event.unread_count), observed_seq - int(state.read_through_seq), 1
        )
        decision = self.policy.evaluate(event, state, moment)
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
            state.wait_until = max(state.wait_until, moment + self.wait_seconds)
        self._save(state)
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

    def accept_user(
        self,
        event: RuntimeInput,
        *,
        event_id: str = "",
        deferred: bool = False,
        now: float | None = None,
    ) -> UserRunReceipt:
        """Record one user turn, then evaluate the run decision.

        The host hook supplies only the reduced inbound event and optional host
        event id. Source construction, pending projection and state transition
        stay inside the runtime write path.
        """
        recorded = None
        if self.recorder is not None:
            seen_at = event.event_time or event.received_at
            at = (
                datetime.datetime.fromtimestamp(
                    float(seen_at), datetime.timezone.utc
                ).isoformat(timespec="seconds")
                if float(seen_at or 0.0) > 0
                else ""
            )
            recorded = self.recorder.record_user(
                session_id=event.session_id,
                text=event.text,
                speaker_id=event.speaker_id,
                event_id=event_id,
                at=at,
                deferred=deferred,
            )
        decision = self.observe(event, now=now)
        return UserRunReceipt(
            decision=decision,
            source_id=recorded.source_id if recorded is not None else "",
            turn_id=recorded.turn_id if recorded is not None else "",
            read_through_seq=(
                None if decision.reason == "stale_event"
                else self.store.get(event.session_id).last_unread_seq
            ),
        )

    def record_reply(
        self,
        *,
        run_id: str,
        session_id: str,
        text: str,
        speaker_id: str,
        turn_id: str = "",
        reply_to: str = "",
        at: str = "",
        recall_ids=(),
    ) -> RecordedReply | None:
        """Write one completed assistant reply through the single recorder."""
        if self.recorder is None:
            return None
        return self.recorder.record_reply(
            run_id=run_id,
            session_id=session_id,
            text=text,
            speaker_id=speaker_id,
            turn_id=turn_id,
            reply_to=reply_to,
            at=at,
            recall_ids=recall_ids,
        )

    def record_delivery(
        self,
        *,
        run_id: str,
        session_id: str,
        decision: str,
        reason: str,
        response_chars: int = 0,
        tool_calls=(),
        user_source_id: str = "",
        assistant_source_id: str = "",
        read_through_seq: int | None = None,
        now: float | None = None,
    ) -> None:
        """Commit one delivered normal run and advance session delivery state."""
        moment = self.clock() if now is None else float(now)
        if self.recorder is not None:
            self.recorder.record_delivery(
                run_id=run_id,
                session_id=session_id,
                decision=decision,
                reason=reason,
                response_chars=response_chars,
                tool_calls=tool_calls,
                user_source_id=user_source_id,
                assistant_source_id=assistant_source_id,
                at=datetime.datetime.fromtimestamp(
                    moment, datetime.timezone.utc
                ).isoformat(timespec="seconds"),
            )
        self.mark_delivered(session_id, moment, read_through_seq=read_through_seq)

    def record_error(
        self,
        *,
        run_id: str,
        session_id: str,
        decision: str,
        reason: str,
        error: object = "",
        user_source_id: str = "",
        assistant_source_id: str = "",
    ) -> None:
        """Write one failed normal run through the single recorder."""
        if self.recorder is None:
            return
        self.recorder.record_error(
            run_id=run_id,
            session_id=session_id,
            decision=decision,
            reason=reason,
            error=error,
            user_source_id=user_source_id,
            assistant_source_id=assistant_source_id,
        )

    async def dispatch_deferred(
        self,
        context: RunContext,
        *,
        now: float | None = None,
        max_attempts: int = 3,
        base_seconds: float = 2.0,
    ) -> RunResult:
        """Claim, generate, send and record one deferred run.

        Host adapters provide the model and sender ports. The runtime owns the
        lifecycle and bounded retry; callers only map the latest Source into a
        RunContext.
        """
        session_id = str(context.session_id or "")
        source_id = str(context.source_id or "")
        text = str(context.text or "").strip()
        moment = self.clock() if now is None else float(now)
        run_id = str(context.run_id or "")
        state = self.store.get(session_id)
        wait_due = state.wait_until > 0 and state.wait_until <= moment
        retry_due = state.next_retry_at > 0 and state.next_retry_at <= moment
        if not (wait_due or retry_due):
            return RunResult(run_id, session_id, False, error="not_due")
        if state.wait_until > moment or (
            state.next_retry_at and state.next_retry_at > moment
        ):
            return RunResult(run_id, session_id, False, error="not_due")
        if not text:
            self.clear_wait(session_id, now)
            return RunResult(run_id, session_id, False, error="empty_source")
        if self.model_gateway is None or self.message_sender is None:
            return RunResult(run_id, session_id, False, error="runtime_port_missing")
        if self.recorder is None:
            return RunResult(run_id, session_id, False, error="recorder_missing")
        if not run_id:
            run_id = self.recorder.new_run_id()

        if (state.last_dispatched_source_id == source_id
                and state.dispatch_attempts >= max(1, int(max_attempts))):
            self.schedule_retry(session_id, moment, state.dispatch_attempts,
                                max_attempts=max_attempts)
            return RunResult(run_id, session_id, False, error="dispatch_dead")
        attempts = self.claim_dispatch(session_id, source_id, moment)
        # Stores may return a live object. Keep a stable, run-local snapshot so
        # old pending markers can be distinguished from newer scheduled work.
        claimed = replace(self.store.get(session_id))
        runtime_input = RuntimeInput(
            session_id=session_id,
            text=text,
            private=False,
            event_time=context.event_time,
            received_at=context.received_at,
        )
        try:
            memory = self.build_context(
                runtime_input, now=moment, reason="deferred"
            )
            reply = await self.model_gateway.complete(
                session_id, text, memory.text or None
            )
            if not str(reply or "").strip():
                raise RuntimeError("empty_response")
            sent = await self.message_sender.send(session_id, reply)
            if sent is False:
                raise RuntimeError("send_failed")
        except (Exception, asyncio.CancelledError) as exc:
            try:
                # Refresh after awaited model/send work; explicit start time
                # remains a lower bound without an advancing injected clock.
                moment = max(moment, float(self.clock()))
                self.schedule_retry(
                    session_id,
                    moment,
                    attempts,
                    max_attempts=max_attempts,
                    base_seconds=base_seconds,
                    claimed=claimed,
                )
                self.recorder.record_deferred_error(
                    run_id=run_id,
                    session_id=session_id,
                    user_source_id=source_id,
                    error=exc,
                    at=datetime.datetime.fromtimestamp(
                        moment, datetime.timezone.utc
                    ).isoformat(timespec="seconds"),
                )
                if self.trace is not None:
                    self.trace.record(
                        "runtime",
                        "deferred_failed",
                        {"error": type(exc).__name__, "attempt": attempts},
                    )
            finally:
                if isinstance(exc, asyncio.CancelledError):
                    raise exc
            return RunResult(
                run_id,
                session_id,
                False,
                error=type(exc).__name__,
            )

        moment = max(moment, float(self.clock()))
        at = datetime.datetime.fromtimestamp(
            moment, datetime.timezone.utc
        ).isoformat(timespec="seconds")
        recorded = self.recorder.record_deferred_reply(
            run_id=run_id,
            session_id=session_id,
            text=reply,
            speaker_id=str(context.bot_id or "bot"),
            user_source_id=source_id,
            at=at,
        )
        self.mark_delivered(
            session_id, moment, claimed=claimed,
            read_through_seq=claimed.last_unread_seq,
        )
        if self.trace is not None:
            self.trace.record(
                "runtime",
                "deferred_delivered",
                {"chars": recorded.response_chars, "attempt": attempts},
            )
        return RunResult(
            run_id,
            session_id,
            True,
            assistant_source_id=recorded.assistant_source_id,
            response_chars=recorded.response_chars,
        )

    def clear_wait(self, session_id: str, now: float | None = None) -> SessionState:
        state = self.store.get(session_id)
        state.wait_until = 0.0
        state.next_retry_at = 0.0
        state.last_seen_at = self.clock() if now is None else now
        self._save(state)
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
        # Retain the durable pending marker while model/send is in flight. The
        # worker owns in-process dedupe; a restarted worker can recover this run.
        state.last_seen_at = moment
        self._save(state)
        return state.dispatch_attempts

    def schedule_retry(self, session_id: str, now: float, attempts: int,
                       max_attempts: int = 3, base_seconds: float = 2.0,
                       cap_seconds: float = 60.0,
                       claimed: SessionState | None = None) -> SessionState:
        """Schedule bounded retry for a failed deferred dispatch."""
        state = self.store.get(session_id)
        if claimed is not None:
            # Do not resurrect input already acknowledged by another delivery,
            # or overwrite work/deadlines installed after this claim. Unchanged
            # retained markers still belong to this failed attempt.
            if (self._pending_changed(state, claimed)
                    or (state.read_through_seq > claimed.read_through_seq
                        and state.read_through_seq >= claimed.last_unread_seq)):
                return state
        tries = max(1, int(attempts))
        if (claimed is not None and state.last_unread_seq > claimed.last_unread_seq
                and tries >= max(1, int(max_attempts))):
            # Exhaustion belongs to the old Source. The retained marker lets
            # the worker pick up the newer Source with its own attempt budget.
            return state
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
        self._save(state)
        return state

    @staticmethod
    def _pending_changed(state: SessionState, claimed: SessionState) -> bool:
        """Whether the pending work belongs to a transition after this claim."""
        return (
            state.last_dispatched_source_id != claimed.last_dispatched_source_id
            or state.wait_until != claimed.wait_until
            or state.next_retry_at != claimed.next_retry_at
        )

    def mark_delivered(
        self,
        session_id: str,
        now: float | None = None,
        *,
        claimed: SessionState | None = None,
        read_through_seq: int | None = None,
    ) -> SessionState:
        moment = self.clock() if now is None else now
        state = self.store.get(session_id)
        state.last_spoke_at = max(state.last_spoke_at, moment)
        state.cooldown_until = max(
            state.cooldown_until,
            state.last_spoke_at + max(0.0, state.reply_cooldown_seconds),
        )
        if read_through_seq is not None:
            cursor = min(state.last_unread_seq, max(0, int(read_through_seq)))
            advanced = cursor > state.read_through_seq
            state.read_through_seq = max(state.read_through_seq, cursor)
            state.unread_count = max(0, state.last_unread_seq - state.read_through_seq)
            current_claim = claimed is not None and not self._pending_changed(state, claimed)
            if cursor >= state.last_unread_seq and (
                current_claim or (claimed is None and advanced)
            ):
                state.wait_until = 0.0
                state.next_retry_at = 0.0
                state.dispatch_attempts = 0
        self._save(state)
        return state
