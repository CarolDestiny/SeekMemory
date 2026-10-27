"""Real SQLite recovery for interrupted deferred work and bounded attempts."""

from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.runtime import (  # noqa: E402
    AgentRuntime, EpisodeRecorder, RepoEpisodeStore, RepoStateStore,
    RunContext, RunRecorder, RuntimeInput, Scheduler, SessionState,
)
from store import open_store  # noqa: E402


class RecoveryTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / "memory.db")
        self.now = 100.0
        self.db = open_store(self.path)
        self.rebuild()
        self.runtime.accept_user(RuntimeInput("s1", "old"), now=95)
        self.context = RunContext("s1", "old", source_id="u1")

    def tearDown(self) -> None:
        self.db.close()
        self.temp.cleanup()

    def rebuild(self) -> None:
        self.store = RepoStateStore(self.db.runtime_state)
        self.runtime = AgentRuntime(
            self.store, clock=lambda: self.now, wait_seconds=5,
            model_gateway=SimpleNamespace(complete=self.complete),
            message_sender=SimpleNamespace(send=self.send),
            recorder=RunRecorder(
                sources=self.db.sources, buffer=None, checkpoint=None,
                episodes=EpisodeRecorder(RepoEpisodeStore(self.db.runtime_episodes)),
            ),
        )

    def restart(self) -> None:
        self.db.close()
        self.db = open_store(self.path)
        self.rebuild()

    async def complete(self, *args) -> str:
        return "reply"

    async def send(self, *args) -> bool:
        return True

    async def cancel_dispatch(self, phase: str, *, max_attempts: int = 3) -> None:
        started = asyncio.Event()

        async def block(*args):
            started.set()
            await asyncio.Event().wait()

        port = self.runtime.model_gateway if phase == "model" else self.runtime.message_sender
        setattr(port, "complete" if phase == "model" else "send", block)
        task = asyncio.create_task(self.runtime.dispatch_deferred(
            self.context, now=self.now, max_attempts=max_attempts,
        ))
        await asyncio.wait_for(started.wait(), timeout=1)
        self.now += 60
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_cancelled_generation_recovers_after_close_and_reopen(self) -> None:
        await self.cancel_dispatch("model")
        self.restart()
        state = self.store.get("s1")
        self.assertEqual(state.dispatch_attempts, 1)
        self.assertEqual(state.next_retry_at, 162)
        self.assertFalse(Scheduler(self.store).due(["s1"], 161))
        self.assertTrue(Scheduler(self.store).due(["s1"], 162))
        self.now = 162
        result = await self.runtime.dispatch_deferred(self.context, now=self.now)
        self.assertTrue(result.delivered)
        self.assertEqual(self.store.get("s1").wait_until, 0)
        self.assertEqual(self.store.get("s1").dispatch_attempts, 0)

    async def test_cancelled_send_recovers_after_close_and_reopen(self) -> None:
        await self.cancel_dispatch("send")
        self.restart()
        self.assertEqual(self.store.get("s1").next_retry_at, 162)
        self.now = 162
        self.assertTrue((await self.runtime.dispatch_deferred(self.context)).delivered)

    async def test_cancellation_propagates_even_if_audit_write_fails(self) -> None:
        def fail_audit(episode):
            raise RuntimeError("audit unavailable")

        self.runtime.recorder.episodes = SimpleNamespace(record=fail_audit)
        await self.cancel_dispatch("model")
        self.restart()
        self.assertEqual(self.store.get("s1").next_retry_at, 162)

    async def test_in_flight_marker_is_durable_before_any_completion(self) -> None:
        started, release = asyncio.Event(), asyncio.Event()

        async def block(*args):
            started.set()
            await release.wait()
            return "reply"

        self.runtime.model_gateway.complete = block
        task = asyncio.create_task(self.runtime.dispatch_deferred(self.context, now=100))
        await asyncio.wait_for(started.wait(), timeout=1)
        try:
            other = open_store(self.path)
            try:
                loaded = RepoStateStore(other.runtime_state).get("s1")
                self.assertTrue(loaded.wait_until > 0 or loaded.next_retry_at > 0)
                self.assertEqual(loaded.dispatch_attempts, 1)
            finally:
                other.close()
        finally:
            release.set()
            await task

    async def test_cancellation_limit_survives_restarts_and_new_source_resets_it(self) -> None:
        for attempt in (1, 2, 3):
            await self.cancel_dispatch("model")
            self.restart()
            state = self.store.get("s1")
            self.assertEqual(state.dispatch_attempts, attempt)
            if attempt < 3:
                self.now = state.next_retry_at
        self.assertEqual(state.wait_until, 0)
        self.assertEqual(state.next_retry_at, 0)
        self.assertEqual(state.last_reason, "dispatch_dead")
        self.assertFalse((await self.runtime.dispatch_deferred(self.context)).delivered)
        self.now += 31
        self.runtime.accept_user(RuntimeInput("s1", "new"), now=self.now)
        self.now += 5
        self.context = RunContext("s1", "new", source_id="u2")
        await self.cancel_dispatch("send")
        self.assertEqual(self.store.get("s1").dispatch_attempts, 1)

    async def test_process_loss_at_last_attempt_cannot_restart_attempt_budget(self) -> None:
        self.runtime.claim_dispatch("s1", "u1", now=100)
        self.runtime.claim_dispatch("s1", "u1", now=100)
        self.runtime.claim_dispatch("s1", "u1", now=100)
        self.restart()
        calls = []

        async def complete(*args):
            calls.append(args)
            return "reply"

        self.runtime.model_gateway.complete = complete
        result = await self.runtime.dispatch_deferred(self.context, now=100)
        self.assertFalse(result.delivered)
        self.assertEqual(result.error, "dispatch_dead")
        self.assertEqual(calls, [])
        self.assertEqual(self.store.get("s1").dispatch_attempts, 3)
        self.assertEqual(self.store.get("s1").wait_until, 0)

    async def test_failure_preserves_new_deadline_but_replaces_old_claim_marker(self) -> None:
        for ambient in (False, True):
            with self.subTest(ambient=ambient):
                self.now = 100
                self.store.put(SessionState("s1", wait_until=100))

                async def fail(*args):
                    self.now = 150
                    self.runtime.accept_user(
                        RuntimeInput("s1", "newer", mentioned=not ambient), now=150,
                    )
                    raise RuntimeError("model_failed")

                self.runtime.model_gateway.complete = fail
                await self.runtime.dispatch_deferred(self.context, now=100)
                state = self.store.get("s1")
                self.assertEqual(state.wait_until, 155 if ambient else 152)

    async def test_old_failure_does_not_resurrect_work_acknowledged_by_normal_reply(self) -> None:
        async def fail(*args):
            self.runtime.record_delivery(
                run_id="normal", session_id="s1", decision="reply", reason="normal",
                read_through_seq=1, now=101,
            )
            raise RuntimeError("model_failed")

        self.runtime.model_gateway.complete = fail
        await self.runtime.dispatch_deferred(self.context, now=100)
        state = self.store.get("s1")
        self.assertEqual(state.wait_until, 0)
        self.assertEqual(state.next_retry_at, 0)
        self.assertEqual(state.unread_count, 0)

    async def test_old_failure_limit_keeps_newer_direct_message_recoverable(self) -> None:
        async def fail(*args):
            self.runtime.accept_user(
                RuntimeInput("s1", "newer", mentioned=True), now=110,
            )
            raise RuntimeError("model_failed")

        self.runtime.model_gateway.complete = fail
        await self.runtime.dispatch_deferred(self.context, now=100, max_attempts=1)
        self.restart()
        self.assertTrue(Scheduler(self.store).due(["s1"], 120))
        result = await self.runtime.dispatch_deferred(
            RunContext("s1", "newer", source_id="u2"), now=120, max_attempts=1,
        )
        self.assertTrue(result.delivered)


if __name__ == "__main__":
    unittest.main()
