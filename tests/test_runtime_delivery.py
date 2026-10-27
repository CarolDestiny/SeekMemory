"""Delivery acknowledges only covered input and uses completion time."""

from __future__ import annotations

import asyncio
import datetime
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.runtime import (  # noqa: E402
    AgentRuntime, InMemoryStateStore, RunContext, RunRecorder, RuntimeInput,
)


class DeliveryTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.now = 100.0
        self.sources = []
        self.episodes = []
        self.store = InMemoryStateStore()
        self.runtime = AgentRuntime(
            self.store, clock=lambda: self.now, wait_seconds=5,
            recorder=RunRecorder(
                sources=SimpleNamespace(append_sources=self.sources.extend),
                buffer=None, checkpoint=None,
                episodes=SimpleNamespace(record=self.episodes.append),
            ),
            model_gateway=SimpleNamespace(complete=self.complete),
            message_sender=SimpleNamespace(send=self.send),
        )

    async def complete(self, *args) -> str:
        self.now += 40
        return "reply"

    async def send(self, *args) -> bool:
        self.now += 20
        return True

    def accept(self, text: str, *, mentioned: bool = False):
        return self.runtime.accept_user(
            RuntimeInput("s1", text, event_time=self.now, mentioned=mentioned),
            now=self.now,
        )

    def deliver(self, receipt, *, now: float | None = None) -> None:
        self.runtime.record_delivery(
            run_id=receipt.source_id, session_id="s1", decision="reply",
            reason="direct_attention", read_through_seq=receipt.read_through_seq,
            now=self.now if now is None else now,
        )

    async def test_slow_generation_and_send_start_cooldown_at_delivery(self) -> None:
        self.accept("old")
        self.now = 105
        result = await self.runtime.dispatch_deferred(
            RunContext("s1", "old", source_id="u1"), now=105,
        )
        self.assertTrue(result.delivered)
        state = self.store.get("s1")
        self.assertEqual(state.last_spoke_at, 165)
        self.assertEqual(state.cooldown_until, 195)
        self.assertEqual(state.unread_count, 0)
        self.assertEqual(state.wait_until, 0)
        self.assertEqual(self.sources[-1].at, "1970-01-01T00:02:45+00:00")
        self.assertEqual(self.episodes[-1].at, self.sources[-1].at)

    async def test_delivery_audit_crosses_midnight_with_clock(self) -> None:
        self.now = datetime.datetime(
            2026, 10, 27, 23, 59, 30, tzinfo=datetime.timezone.utc,
        ).timestamp()
        self.accept("old")
        self.now += 5
        await self.runtime.dispatch_deferred(RunContext("s1", "old"), now=self.now)
        self.assertEqual(self.sources[-1].at, "2026-10-28T00:00:35+00:00")
        self.assertEqual(self.episodes[-1].at, self.sources[-1].at)

    async def test_slow_failure_backs_off_from_failure_time(self) -> None:
        for phase in ("model", "send"):
            with self.subTest(phase=phase):
                self.setUp()
                self.accept("old")
                self.now = 105

                async def fail(*args):
                    self.now = 165
                    raise RuntimeError("private detail")

                port = (self.runtime.model_gateway if phase == "model"
                        else self.runtime.message_sender)
                setattr(port, "complete" if phase == "model" else "send", fail)
                result = await self.runtime.dispatch_deferred(
                    RunContext("s1", "old"), now=105,
                )
                self.assertFalse(result.delivered)
                state = self.store.get("s1")
                self.assertEqual(state.next_retry_at, 167)
                self.assertEqual(self.episodes[-1].at, "1970-01-01T00:02:45+00:00")
                self.assertEqual(self.episodes[-1].error, "RuntimeError")

    async def test_old_normal_reply_keeps_newer_unread_and_wait(self) -> None:
        first = self.accept("first", mentioned=True)
        self.now = 101
        self.accept("second")
        self.now = 105
        self.deliver(first)
        state = self.store.get("s1")
        self.assertEqual(state.read_through_seq, first.read_through_seq)
        self.assertEqual(state.unread_count, 1)
        self.assertEqual(state.wait_until, 106)
        self.assertEqual(state.last_spoke_at, 105)
        self.assertEqual(self.episodes[-1].at, "1970-01-01T00:01:45+00:00")

    async def test_duplicate_out_of_order_delivery_never_moves_cursor_back(self) -> None:
        first = self.accept("first", mentioned=True)
        self.now = 101
        second = self.accept("second", mentioned=True)
        self.now = 105
        self.deliver(second)
        self.now = 140
        self.accept("third")
        self.deliver(first, now=104)
        self.deliver(second, now=105)
        state = self.store.get("s1")
        self.assertEqual(state.read_through_seq, second.read_through_seq)
        self.assertEqual(state.unread_count, 1)
        self.assertEqual(state.wait_until, 145)
        self.assertEqual(state.last_spoke_at, 105)

    async def test_missing_acknowledgement_only_updates_delivery_timing(self) -> None:
        self.accept("pending")
        self.runtime.record_delivery(
            run_id="legacy", session_id="s1", decision="reply", reason="legacy", now=110,
        )
        state = self.store.get("s1")
        self.assertEqual(state.last_spoke_at, 110)
        self.assertEqual(state.unread_count, 1)
        self.assertEqual(state.read_through_seq, 0)
        self.assertEqual(state.wait_until, 105)

    async def test_stale_receipt_cannot_acknowledge_current_messages(self) -> None:
        self.accept("current")
        stale = self.runtime.accept_user(
            RuntimeInput("s1", "stale", event_time=90), now=110,
        )
        self.assertIsNone(stale.read_through_seq)
        self.deliver(stale)
        self.assertEqual(self.store.get("s1").unread_count, 1)

    async def test_deferred_reply_confirms_only_input_seen_before_generation(self) -> None:
        first = self.accept("old")
        self.now = 105

        async def interleave(*args):
            self.now = 110
            self.accept("newer")
            return "reply"

        self.runtime.model_gateway.complete = interleave
        await self.runtime.dispatch_deferred(RunContext("s1", "old"), now=105)
        state = self.store.get("s1")
        self.assertEqual(state.read_through_seq, first.read_through_seq)
        self.assertEqual(state.unread_count, 1)
        self.assertEqual(state.wait_until, 115)


if __name__ == "__main__":
    unittest.main()
