"""Deferred delivery preserves unread traffic and recoverable write-back."""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.runtime import (
    AgentRuntime, DBStateStore, DBEpisodeStore, EpisodeRecorder, InMemoryStateStore,
    MemoryContext, RunContext, RunRecorder, RuntimeInput,
)
from store.db import DB
from core.source import Source
from app.runtime.deferred_store import DBDeferredStore, DeferredReply, InMemoryDeferredStore


class DeferredRecoveryTest(unittest.TestCase):
    def make_runtime(self, *, store=None, outbox=None, fail_write=False, model_hook=None):
        store = store or InMemoryStateStore()
        seen = []
        sent = []
        writes = []

        class Model:
            async def complete(self, session_id, prompt, system_prompt=None):
                if model_hook is not None:
                    model_hook(runtime)
                return "protected reply"

        class Sender:
            async def send(self, session_id, text):
                sent.append(text)
                return True

        class Recorder:
            failed = fail_write

            def new_run_id(self):
                return "run-1"

            def record_deferred_reply(self, **kwargs):
                writes.append(kwargs)
                if self.failed:
                    raise OSError("private database detail")
                return SimpleNamespace(response_chars=len(kwargs["text"]), assistant_source_id="a1")

            def record_deferred_error(self, **kwargs):
                pass

        recorder = Recorder()
        kwargs = {} if outbox is None else {"deferred_store": outbox}
        runtime = AgentRuntime(
            store, clock=lambda: 11, wait_seconds=5,
            model_gateway=Model(), message_sender=Sender(), recorder=recorder,
            memory_context=SimpleNamespace(build_context=lambda event: (
                seen.append(event) or MemoryContext(info={"final_ids": ("m1",)})
            )), **kwargs,
        )
        return runtime, sent, writes, seen, recorder

    def test_sending_old_reply_preserves_new_traffic(self):
        runtime, sent, _, _, _ = self.make_runtime(model_hook=lambda rt: rt.observe(
            RuntimeInput("s1", "new traffic", speaker_id="u2", at=12)
        ))
        runtime.observe(RuntimeInput("s1", "old traffic", at=5))
        result = asyncio.run(runtime.dispatch_deferred(RunContext("s1", "old traffic", source_id="u1", at=11)))
        self.assertTrue(result.delivered)
        self.assertEqual(sent, ["protected reply"])
        state = runtime.store.get("s1")
        self.assertEqual(state.read_through_seq, 1)
        self.assertEqual(state.unread_count, 1)
        self.assertEqual(state.wait_until, 17)
        self.assertEqual(state.next_retry_at, 0)

    def test_sent_write_failure_retries_only_writeback(self):
        runtime, sent, writes, _, recorder = self.make_runtime(fail_write=True)
        runtime.observe(RuntimeInput("s1", "old traffic", at=5))
        result = asyncio.run(runtime.dispatch_deferred(RunContext("s1", "old traffic", source_id="u1", at=11)))
        self.assertTrue(result.delivered)
        self.assertEqual(result.error, "writeback_pending")
        recorder.failed = False
        result = asyncio.run(runtime.dispatch_deferred(RunContext("s1", "later traffic", source_id="u2", at=20)))
        self.assertTrue(result.delivered)
        self.assertEqual(sent, ["protected reply"])
        self.assertEqual(len(writes), 2)
        self.assertEqual(writes[1]["user_source_id"], "u1")

    def test_deferred_recall_keeps_speaker(self):
        runtime, _, _, seen, _ = self.make_runtime()
        runtime.observe(RuntimeInput("s1", "old traffic", at=5))
        asyncio.run(runtime.dispatch_deferred(RunContext("s1", "old traffic", source_id="u1", at=11, speaker_id="actual-user")))
        self.assertEqual(seen[0].speaker_id, "actual-user")

    def test_latest_source_includes_speaker_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            db = DB(os.path.join(temp, "memory.db"))
            try:
                db.append_sources([Source("u1", "turn1", "s1", "actual-user", "user", "hello", "2026-01-01")])
                self.assertEqual(db.latest_user_source("s1")["speaker_id"], "actual-user")
            finally:
                db.close()

    def test_latest_source_breaks_same_time_ties_by_insertion(self):
        db = DB(":memory:")
        self.addCleanup(db.close)
        db.append_sources([
            Source("z-old", "turn1", "s1", "old-user", "user", "old traffic", "2026-01-01T00:00:00"),
            Source("a-new", "turn2", "s1", "new-user", "user", "new traffic", "2026-01-01T00:00:00"),
        ])
        source = db.latest_user_source("s1")
        self.assertEqual(source["id"], "a-new")
        self.assertEqual(source["text"], "new traffic")
        self.assertEqual(source["speaker_id"], "new-user")

    def test_sent_writeback_survives_restart_without_host_ports(self):
        with tempfile.TemporaryDirectory() as temp:
            path = os.path.join(temp, "memory.db")
            db = DB(path)
            runtime, sent, _, _, _ = self.make_runtime(
                store=DBStateStore(db), outbox=DBDeferredStore(db), fail_write=True,
            )
            runtime.observe(RuntimeInput("s1", "old traffic", at=5))
            result = asyncio.run(runtime.dispatch_deferred(RunContext("s1", "old traffic", source_id="u1", at=11)))
            self.assertEqual(result.error, "writeback_pending")
            db.close()
            db = DB(path)
            try:
                resumed, resumed_sends, writes, _, _ = self.make_runtime(
                    store=DBStateStore(db), outbox=DBDeferredStore(db),
                )
                resumed.model_gateway = None
                resumed.message_sender = None
                results = resumed.recover_deliveries(20)
                self.assertEqual(len(results), 1)
                self.assertTrue(results[0].delivered)
                self.assertEqual(sent, ["protected reply"])
                self.assertEqual(resumed_sends, [])
                self.assertEqual(writes[0]["user_source_id"], "u1")
                self.assertEqual(DBDeferredStore(db).sent(), ())
                self.assertEqual(resumed.store.get("s1").read_through_seq, 1)
            finally:
                db.close()

    def test_sent_receipt_write_failure_blocks_resend_after_restart(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        db = DB(os.path.join(temp.name, "memory.db"))
        self.addCleanup(db.close)
        outbox = DBDeferredStore(db)
        original = outbox.put

        def failing_receipt(row):
            if row.status == "sent":
                raise OSError("receipt failure")
            return original(row)

        outbox.put = failing_receipt
        runtime, sent, writes, _, _ = self.make_runtime(outbox=outbox)
        runtime.observe(RuntimeInput("s1", "old traffic", at=5))
        result = asyncio.run(runtime.dispatch_deferred(RunContext("s1", "old traffic", source_id="u1", at=11)))
        self.assertTrue(result.delivered)
        self.assertEqual(result.error, "delivery_unconfirmed")
        resumed, resumed_sends, _, _, _ = self.make_runtime(outbox=DBDeferredStore(db))
        result = asyncio.run(resumed.dispatch_deferred(RunContext("s1", "later traffic", at=20)))
        self.assertEqual(result.error, "delivery_unconfirmed")
        self.assertEqual(sent, ["protected reply"])
        self.assertEqual(resumed_sends, [])
        self.assertEqual(writes, [])

    def test_outbox_write_failure_prevents_send(self):
        outbox = InMemoryDeferredStore()
        outbox.put = lambda row: (_ for _ in ()).throw(OSError("outbox unavailable"))
        runtime, sent, _, _, _ = self.make_runtime(outbox=outbox)
        runtime.observe(RuntimeInput("s1", "old traffic", at=5))
        result = asyncio.run(runtime.dispatch_deferred(RunContext("s1", "old traffic", at=11)))
        self.assertFalse(result.delivered)
        self.assertEqual(sent, [])
        self.assertGreater(runtime.store.get("s1").next_retry_at, 11)

    def test_transport_timeout_preserves_uncertain_intent(self):
        runtime, _, _, _, _ = self.make_runtime()

        async def timed_out(session, text):
            raise TimeoutError("platform may have accepted message")

        runtime.message_sender.send = timed_out
        runtime.observe(RuntimeInput("s1", "old traffic", at=5))
        context = RunContext("s1", "old traffic", at=11)
        first = asyncio.run(runtime.dispatch_deferred(context))
        second = asyncio.run(runtime.dispatch_deferred(context))
        self.assertEqual(first.error, "delivery_unconfirmed")
        self.assertEqual(second.error, "delivery_unconfirmed")
        self.assertIsNotNone(runtime.deferred.outbox.get("s1"))

    def test_explicit_rejection_has_bounded_retry(self):
        runtime, _, _, _, _ = self.make_runtime()

        async def rejected(session, text):
            return False

        runtime.message_sender.send = rejected
        runtime.observe(RuntimeInput("s1", "old traffic", at=5))
        for now in (11, 20):
            result = asyncio.run(runtime.dispatch_deferred(RunContext("s1", "old traffic", source_id="u1", at=now), max_attempts=2))
            self.assertFalse(result.delivered)
        state = runtime.store.get("s1")
        self.assertEqual(state.next_retry_at, 0)
        self.assertEqual(state.last_reason, "dispatch_dead")

    def test_old_writeback_preserves_newer_wait(self):
        runtime, _, _, _, recorder = self.make_runtime(fail_write=True)
        runtime.observe(RuntimeInput("s1", "old traffic", at=5))
        asyncio.run(runtime.dispatch_deferred(RunContext("s1", "old traffic", at=11)))
        runtime.observe(RuntimeInput("s1", "new traffic", at=12))
        recorder.failed = False
        runtime.recover_deliveries(20)
        state = runtime.store.get("s1")
        self.assertEqual(state.unread_count, 1)
        self.assertEqual(state.wait_until, 17)
        self.assertEqual(state.next_retry_at, 0)

    def test_source_write_failure_after_send_is_recoverable(self):
        with tempfile.TemporaryDirectory() as temp:
            db = DB(os.path.join(temp, "memory.db"))
            try:
                runtime, sent, _, _, _ = self.make_runtime(outbox=DBDeferredStore(db))
                runtime.recorder = RunRecorder(
                    db=db, buffer=None, checkpoint=None,
                    episodes=EpisodeRecorder(DBEpisodeStore(db)),
                )
                append = db.append_sources
                db.append_sources = lambda rows: (_ for _ in ()).throw(OSError("write failed"))
                runtime.observe(RuntimeInput("s1", "old traffic", at=5))
                first = asyncio.run(runtime.dispatch_deferred(RunContext("s1", "old traffic", source_id="u1", at=11)))
                self.assertTrue(first.delivered)
                self.assertEqual(first.error, "writeback_pending")
                db.append_sources = append
                result = runtime.recover_deliveries(20)[0]
                self.assertTrue(result.delivered)
                self.assertEqual(result.error, "")
                self.assertEqual(sent, ["protected reply"])
                self.assertEqual(len(db.sources_by_ids([result.assistant_source_id])), 1)
                self.assertEqual(len(db.list_runtime_episodes("s1")), 1)
            finally:
                db.close()

    def test_generation_cancel_restores_retry(self):
        runtime, sent, _, _, _ = self.make_runtime()

        async def cancelled(session, prompt, system_prompt=None):
            raise asyncio.CancelledError()

        runtime.model_gateway.complete = cancelled
        runtime.observe(RuntimeInput("s1", "old traffic", at=5))
        with self.assertRaises(asyncio.CancelledError):
            asyncio.run(runtime.dispatch_deferred(RunContext("s1", "old traffic", at=11)))
        self.assertEqual(sent, [])
        self.assertGreater(runtime.store.get("s1").next_retry_at, 11)

    def test_send_cancel_retains_uncertain_intent(self):
        runtime, _, _, _, _ = self.make_runtime()

        async def cancelled(session, text):
            raise asyncio.CancelledError()

        runtime.message_sender.send = cancelled
        runtime.observe(RuntimeInput("s1", "old traffic", at=5))
        with self.assertRaises(asyncio.CancelledError):
            asyncio.run(runtime.dispatch_deferred(RunContext("s1", "old traffic", at=11)))
        self.assertEqual(runtime.deferred.outbox.get("s1").status, "sending")
        result = asyncio.run(runtime.dispatch_deferred(RunContext("s1", "new traffic", at=20)))
        self.assertEqual(result.error, "delivery_unconfirmed")

    def test_delivery_state_fault_retains_receipt_until_state_recovers(self):
        for method_name in ("get_runtime_state", "put_runtime_state"):
            with self.subTest(method=method_name), tempfile.TemporaryDirectory() as temp:
                db = DB(os.path.join(temp, "memory.db"))
                try:
                    outbox = DBDeferredStore(db)
                    state_store = DBStateStore(db)
                    runtime, sent, _, _, recorder = self.make_runtime(
                        store=state_store, outbox=outbox,
                    )
                    runtime.observe(RuntimeInput("s1", "old traffic", at=5))
                    original = getattr(db, method_name)
                    original_record = recorder.record_deferred_reply

                    def fail_state(**kwargs):
                        result = original_record(**kwargs)
                        setattr(db, method_name, lambda *args, **kw: (
                            (_ for _ in ()).throw(OSError("state unavailable"))
                        ))
                        return result

                    recorder.record_deferred_reply = fail_state
                    result = asyncio.run(runtime.dispatch_deferred(RunContext("s1", "old traffic", at=11)))
                    self.assertEqual(result.error, "writeback_pending")
                    self.assertEqual(len(outbox.sent()), 1)
                    setattr(db, method_name, original)
                    recorder.record_deferred_reply = original_record
                    result = runtime.recover_deliveries(20)[0]
                    self.assertEqual(result.error, "")
                    self.assertEqual(state_store.get("s1").read_through_seq, 1)
                    self.assertEqual(sent, ["protected reply"])
                    self.assertEqual(outbox.sent(), ())
                finally:
                    db.close()

    def test_generation_claim_survives_restart_until_lease_expires(self):
        with tempfile.TemporaryDirectory() as temp:
            path = os.path.join(temp, "memory.db")
            db = DB(path)
            runtime, _, _, _, _ = self.make_runtime(
                store=DBStateStore(db), outbox=DBDeferredStore(db),
            )
            runtime.observe(RuntimeInput("s1", "old traffic", at=5))
            self.assertEqual(runtime.claim_dispatch("s1", "u1", now=11), 1)
            self.assertEqual(runtime.store.get("s1").next_retry_at, 71)
            db.close()
            db = DB(path)
            try:
                runtime, sent, _, seen, _ = self.make_runtime(
                    store=DBStateStore(db), outbox=DBDeferredStore(db),
                )
                early = asyncio.run(runtime.dispatch_deferred(RunContext("s1", "old traffic", source_id="u1", at=70)))
                self.assertEqual(early.error, "not_due")
                recovered = asyncio.run(runtime.dispatch_deferred(RunContext("s1", "old traffic", source_id="u1", at=72)))
                self.assertTrue(recovered.delivered)
                self.assertEqual(sent, ["protected reply"])
                self.assertEqual(len(seen), 1)
                self.assertEqual(runtime.store.get("s1").read_through_seq, 1)
            finally:
                db.close()

    def test_crashed_generation_claims_still_exhaust_attempt_budget(self):
        runtime, sent, _, seen, _ = self.make_runtime()
        runtime.observe(RuntimeInput("s1", "old traffic", at=5))
        for now in (11, 72, 133):
            runtime.claim_dispatch("s1", "u1", now=now)
        result = asyncio.run(runtime.dispatch_deferred(
            RunContext("s1", "old traffic", source_id="u1", at=200), max_attempts=3,
        ))
        self.assertEqual(result.error, "dispatch_dead")
        self.assertEqual(runtime.store.get("s1").next_retry_at, 0)
        self.assertEqual(sent, [])
        self.assertEqual(seen, [])

    def test_failed_old_generation_releases_lease_for_new_traffic(self):
        def new_then_fail(runtime):
            runtime.observe(RuntimeInput("s1", "new traffic", at=12))
            raise RuntimeError("model failed")

        runtime, sent, _, _, _ = self.make_runtime(model_hook=new_then_fail)
        runtime.observe(RuntimeInput("s1", "old traffic", at=5))
        asyncio.run(runtime.dispatch_deferred(RunContext("s1", "old traffic", source_id="u1", at=11)))
        state = runtime.store.get("s1")
        self.assertEqual(state.wait_until, 17)
        self.assertEqual(state.next_retry_at, 0)
        self.assertEqual(state.unread_count, 2)
        self.assertEqual(sent, [])


if __name__ == "__main__":
    unittest.main()
