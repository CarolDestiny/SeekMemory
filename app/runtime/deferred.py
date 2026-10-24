"""Deferred generation, platform delivery and recoverable completed-run write-back."""

from __future__ import annotations

import asyncio
import datetime
from dataclasses import replace
from typing import TYPE_CHECKING

from .contracts import RunContext, RunResult, RuntimeInput
from .deferred_store import DeferredReply, DeferredStore

if TYPE_CHECKING:
    from .runtime import AgentRuntime


class DeferredDispatcher:
    def __init__(self, runtime: AgentRuntime, outbox: DeferredStore) -> None:
        self.runtime = runtime
        self.outbox = outbox

    async def dispatch(self, context: RunContext, *, max_attempts: int,
                       base_seconds: float) -> RunResult:
        runtime = self.runtime
        session = str(context.session_id or "")
        now = float(context.at or runtime.clock())
        run_id = str(context.run_id or "")
        try:
            pending = self.outbox.get(session)
        except Exception as exc:
            return RunResult(run_id, session, False, error=type(exc).__name__)
        if pending is not None:
            if pending.status == "sent":
                return self.finish(pending, now)
            # The host may have accepted the send before a process/storage failure.
            # Without a transport receipt it is unsafe to send the body again.
            return RunResult(pending.run_id, session, False, error="delivery_unconfirmed")
        state = runtime.store.get(session)
        if getattr(runtime.store, "last_error", ""):
            return RunResult(run_id, session, False, error="runtime_state_read_failed")
        due = (0 < state.wait_until <= now or 0 < state.next_retry_at <= now)
        if not due or state.wait_until > now or state.next_retry_at > now:
            return RunResult(run_id, session, False, error="not_due")
        text = str(context.text or "").strip()
        if not text:
            runtime.clear_wait(session, now)
            return RunResult(run_id, session, False, error="empty_source")
        if runtime.model_gateway is None or runtime.message_sender is None:
            return RunResult(run_id, session, False, error="runtime_port_missing")
        if runtime.recorder is None:
            return RunResult(run_id, session, False, error="recorder_missing")
        if (state.last_dispatched_source_id == str(context.source_id or "")
                and state.dispatch_attempts >= max(1, int(max_attempts))):
            runtime.schedule_retry(session, now, state.dispatch_attempts,
                                   max_attempts=max_attempts,
                                   read_through_seq=state.last_unread_seq)
            return RunResult(run_id, session, False, error="dispatch_dead")
        run_id = run_id or runtime.recorder.new_run_id()
        watermark = state.last_unread_seq
        try:
            attempts = runtime.claim_dispatch(session, context.source_id, now)
        except Exception as exc:
            self.trace("deferred_failed", error=type(exc).__name__)
            return RunResult(run_id, session, False, error=type(exc).__name__)
        try:
            memory = runtime.build_context(RuntimeInput(
                session_id=session, text=text, speaker_id=context.speaker_id,
                private=False, at=now,
            ))
            reply = await runtime.model_gateway.complete(session, text, memory.text or None)
            if not str(reply or "").strip():
                raise RuntimeError("empty_response")
            pending = DeferredReply(
                run_id, session, str(reply), str(context.bot_id or "bot"),
                str(context.source_id or ""), watermark,
                datetime.datetime.now().isoformat(timespec="seconds"),
                tuple(memory.info.get("final_ids") or ()),
                tuple(memory.info.get("designated_ids") or ()),
                designated_revisions=dict(memory.info.get("designated_revisions") or {}),
            )
            # Persist intent before crossing the external delivery boundary.
            self.outbox.put(pending)
        except asyncio.CancelledError:
            self.failed(context, run_id, now, attempts, watermark,
                        RuntimeError("generation_cancelled"), max_attempts, base_seconds)
            raise
        except Exception as exc:
            return self.failed(context, run_id, now, attempts, watermark,
                               exc, max_attempts, base_seconds)
        try:
            sent = await runtime.message_sender.send(session, reply)
        except asyncio.CancelledError:
            self.trace("deferred_unconfirmed", error="CancelledError")
            raise
        except Exception as exc:
            # A timeout can happen after the remote platform accepted the send.
            # Keep the intent and require a receipt instead of sending again.
            self.trace("deferred_unconfirmed", error=type(exc).__name__)
            return RunResult(run_id, session, False, error="delivery_unconfirmed")
        if sent is False:
            try:
                self.outbox.remove(run_id)
            except Exception as exc:
                self.trace("deferred_unconfirmed", error=type(exc).__name__)
                return RunResult(run_id, session, False, error="delivery_unconfirmed")
            return self.failed(context, run_id, now, attempts, watermark,
                               RuntimeError("send_failed"), max_attempts, base_seconds)
        delivered = replace(pending, status="sent", sent_at=max(now, float(runtime.clock() or now)))
        try:
            self.outbox.put(delivered)
        except Exception as exc:
            self.trace("deferred_unconfirmed", error=type(exc).__name__)
            return RunResult(run_id, session, True, response_chars=len(reply),
                             error="delivery_unconfirmed")
        return self.finish(delivered, now)

    def failed(self, context: RunContext, run_id: str, now: float,
               attempts: int, watermark: int, error: Exception,
               max_attempts: int, base_seconds: float) -> RunResult:
        runtime = self.runtime
        runtime.schedule_retry(context.session_id, now, attempts,
                               max_attempts=max_attempts, base_seconds=base_seconds,
                               read_through_seq=watermark)
        try:
            runtime.recorder.record_deferred_error(
                run_id=f"{run_id}:failed:{attempts}", session_id=context.session_id,
                user_source_id=context.source_id, error=error,
                at=datetime.datetime.now().isoformat(timespec="seconds"),
            )
        except Exception:
            pass
        self.trace("deferred_failed", error=type(error).__name__, attempt=attempts)
        return RunResult(run_id, context.session_id, False, error=type(error).__name__)

    def finish(self, pending: DeferredReply, now: float) -> RunResult:
        """Retry only local writes after confirmed send; never invoke host ports."""
        runtime = self.runtime
        try:
            if runtime.recorder is None:
                raise RuntimeError("recorder_missing")
            recorded = runtime.recorder.record_deferred_reply(
                run_id=pending.run_id, session_id=pending.session_id,
                text=pending.text, speaker_id=pending.speaker_id,
                user_source_id=pending.user_source_id, at=pending.at,
                recall_ids=pending.recall_ids, designated_ids=pending.designated_ids,
                designated_revisions=pending.designated_revisions,
            )
            runtime.mark_delivered(pending.session_id, pending.sent_at or now,
                                   read_through_seq=pending.read_through_seq,
                                   dispatched_source_id=pending.user_source_id)
            self.outbox.remove(pending.run_id)
        except Exception as exc:
            self.trace("deferred_writeback_pending", error=type(exc).__name__)
            return RunResult(pending.run_id, pending.session_id, True,
                             response_chars=len(pending.text), error="writeback_pending")
        self.trace("deferred_delivered", chars=recorded.response_chars)
        return RunResult(pending.run_id, pending.session_id, True,
                         assistant_source_id=recorded.assistant_source_id,
                         response_chars=recorded.response_chars)

    def recover(self, now: float) -> tuple[RunResult, ...]:
        """Complete known delivered runs, including while generation gate is off."""
        try:
            pending = self.outbox.sent()
        except Exception as exc:
            self.trace("deferred_recovery_failed", error=type(exc).__name__)
            return ()
        return tuple(self.finish(row, now) for row in pending)

    def trace(self, status: str, **context: str | int) -> None:
        if self.runtime.trace is not None:
            self.runtime.trace.record("runtime", status, context)
