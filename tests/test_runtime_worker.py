"""One worker concurrency boundary for queued, direct and scanned dispatch."""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.runtime import (  # noqa: E402
    AgentRuntime, InMemoryStateStore, RunContext, RunRecorder, RuntimeWorker,
    Scheduler, SessionState,
)


class WorkerTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.now = 100.0
        self.enabled = True
        self.active = 0
        self.max_active = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.sessions = []
        self.context_times = []
        self.store = InMemoryStateStore()
        for session in ("s1", "s2", "s3"):
            self.store.put(SessionState(session, wait_until=100))
        self.runtime = AgentRuntime(
            self.store, clock=lambda: self.now,
            recorder=RunRecorder(sources=None, buffer=None, checkpoint=None, episodes=None),
            model_gateway=SimpleNamespace(complete=self.complete),
            message_sender=SimpleNamespace(send=self.send),
        )
        self.worker = RuntimeWorker(
            runtime=self.runtime, scheduler=Scheduler(self.store),
            enabled=lambda: self.enabled, session_ids=lambda limit: ["s2", "s3"],
            run_context=self.context, interval_seconds=lambda: 1,
            max_attempts=lambda: 3, base_seconds=lambda: 2, max_concurrency=1,
            clock=lambda: self.now,
        )

    def context(self, session_id: str, now: float) -> RunContext:
        self.context_times.append(now)
        return RunContext(session_id, "hello", source_id="u1")

    async def complete(self, session_id: str, *args) -> str:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.sessions.append(session_id)
        self.started.set()
        try:
            await self.release.wait()
            return "reply"
        finally:
            self.active -= 1

    async def send(self, *args) -> bool:
        return True

    async def first_dispatch(self):
        task = asyncio.create_task(self.worker.dispatch("s1", 100))
        await asyncio.wait_for(self.started.wait(), timeout=1)
        return task

    async def test_direct_calls_and_ticks_share_one_concurrency_limit(self) -> None:
        first = await self.first_dispatch()
        direct = asyncio.create_task(self.worker.dispatch("s2", 100))
        tick = asyncio.create_task(self.worker.tick(now=100))
        await asyncio.sleep(0)
        peak_while_blocked = self.max_active
        self.release.set()
        await asyncio.gather(first, direct, tick)
        self.assertEqual(peak_while_blocked, 1)
        self.assertEqual(self.max_active, 1)
        self.assertEqual(sorted(self.sessions), ["s1", "s2", "s3"])

    async def test_duplicate_session_is_rejected_while_queued(self) -> None:
        first = await self.first_dispatch()
        queued = asyncio.create_task(self.worker.dispatch("s2", 100))
        await asyncio.sleep(0)
        duplicate = await self.worker.dispatch("s2", 100)
        self.release.set()
        await asyncio.gather(first, queued)
        self.assertIsNone(duplicate)
        self.assertEqual(self.sessions.count("s2"), 1)

    async def test_cancelled_queued_call_releases_session_for_later_dispatch(self) -> None:
        first = await self.first_dispatch()
        queued = asyncio.create_task(self.worker.dispatch("s2", 100))
        await asyncio.sleep(0)
        queued.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await queued
        attempts_before_retry = self.store.get("s2").dispatch_attempts
        self.release.set()
        await first
        result = await self.worker.dispatch("s2", 100)
        self.assertEqual(attempts_before_retry, 0)
        self.assertTrue(result.delivered)

    async def test_queued_dispatch_rechecks_gate_after_acquiring_slot(self) -> None:
        first = await self.first_dispatch()
        queued = asyncio.create_task(self.worker.dispatch("s2", 100))
        await asyncio.sleep(0)
        self.enabled = False
        self.release.set()
        await first
        self.assertIsNone(await queued)
        self.assertEqual(self.sessions, ["s1"])

    async def test_queued_dispatch_rechecks_changed_deadline(self) -> None:
        first = await self.first_dispatch()
        queued = asyncio.create_task(self.worker.dispatch("s2", 100))
        await asyncio.sleep(0)
        self.store.get("s2").wait_until = 200
        self.release.set()
        await first
        self.assertIsNone(await queued)
        self.assertEqual(self.sessions, ["s1"])

    async def test_queued_context_uses_fresh_clock_at_acquired_slot(self) -> None:
        first = await self.first_dispatch()
        queued = asyncio.create_task(self.worker.dispatch("s2", 100))
        await asyncio.sleep(0)
        self.now = 160
        self.release.set()
        await asyncio.gather(first, queued)
        self.assertEqual(self.context_times, [100, 160])

    async def test_cancelled_active_call_releases_worker_slot(self) -> None:
        first = await self.first_dispatch()
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        self.release.set()
        self.assertTrue((await self.worker.dispatch("s2", 100)).delivered)
        self.now = 102
        self.assertTrue((await self.worker.dispatch("s1", 102)).delivered)


if __name__ == "__main__":
    unittest.main()
