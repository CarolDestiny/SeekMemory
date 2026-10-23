"""Pure AgentRuntime contracts, wake policy and social-state tests."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.runtime import (  # noqa: E402
    AgentRuntime,
    InMemoryStateStore,
    JsonStateStore,
    MemoryContext,
    RuntimeInput,
    SocialState,
    WakeAction,
    WakePolicy,
)


class Trace:
    def __init__(self) -> None:
        self.rows = []

    def record(self, kind, status, context=None):
        self.rows.append((kind, status, context or {}))


class WakePolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = WakePolicy()
        self.state = SocialState(session_id="s1")

    def test_empty_text_is_ignored(self) -> None:
        self.assertEqual(
            self.policy.evaluate(RuntimeInput("s1", ""), self.state, 10).action,
            WakeAction.IGNORE,
        )

    def test_direct_attention_replies(self) -> None:
        decision = self.policy.evaluate(
            RuntimeInput("s1", "hello", mentioned=True), self.state, 10
        )
        self.assertEqual(decision.action, WakeAction.REPLY)
        self.assertEqual(decision.reason, "direct_attention")

    def test_question_replies_without_mention(self) -> None:
        self.assertEqual(
            self.policy.evaluate(
                RuntimeInput("s1", "what time?", question=True), self.state, 10
            ).action,
            WakeAction.REPLY,
        )

    def test_cooldown_ignores_ambient_message(self) -> None:
        self.state.last_spoke_at = 100
        self.state.reply_cooldown_seconds = 30
        decision = self.policy.evaluate(RuntimeInput("s1", "ambient", at=110), self.state, 110)
        self.assertEqual(decision.action, WakeAction.IGNORE)
        self.assertEqual(decision.reason, "reply_cooldown")

    def test_quiet_window_ignores_direct_message(self) -> None:
        self.state.quiet_until = 200
        decision = self.policy.evaluate(
            RuntimeInput("s1", "hello", mentioned=True, at=150), self.state, 150
        )
        self.assertEqual(decision.action, WakeAction.IGNORE)
        self.assertEqual(decision.reason, "quiet_window")

    def test_ambient_message_observes(self) -> None:
        self.assertEqual(
            self.policy.evaluate(RuntimeInput("s1", "ambient", at=10), self.state, 10).action,
            WakeAction.OBSERVE,
        )

    def test_proactive_probability_one(self) -> None:
        self.state.proactive_idle_seconds = 60
        self.state.proactive_probability = 1.0
        decision = self.policy.proactive(self.state, 120, 1000)
        self.assertEqual(decision.action, WakeAction.PROACTIVE)


class AgentRuntimeTest(unittest.TestCase):
    def test_observe_updates_state_and_trace(self) -> None:
        store = InMemoryStateStore()
        trace = Trace()
        runtime = AgentRuntime(store, trace=trace, clock=lambda: 100)
        decision = runtime.observe(
            RuntimeInput("s1", "hello", mentioned=True, unread_count=3)
        )
        state = store.get("s1")
        self.assertEqual(decision.action, WakeAction.REPLY)
        self.assertEqual(state.last_action, "reply")
        self.assertEqual(state.unread_count, 3)
        self.assertEqual(len(trace.rows), 1)
        self.assertNotIn("hello", str(trace.rows[0]))

    def test_memory_context_port_is_delegated(self) -> None:
        seen = []
        expected = MemoryContext(text="block", info={"final_ids": ("a1",)})

        class Memory:
            def build_context(self, event):
                seen.append(event)
                return expected

        event = RuntimeInput("s1", "hello")
        runtime = AgentRuntime(InMemoryStateStore(), memory_context=Memory())
        context = runtime.build_context(event)
        self.assertIs(context, expected)
        self.assertIs(seen[0], event)
        self.assertEqual(context.text, "block")
        self.assertEqual(context.info["final_ids"], ("a1",))

    def test_missing_memory_context_returns_empty_context(self) -> None:
        runtime = AgentRuntime(InMemoryStateStore())
        first = runtime.build_context(RuntimeInput("s1", "hello"))
        second = runtime.build_context(RuntimeInput("s1", "again"))
        self.assertEqual(first.text, "")
        self.assertEqual(first.info, {})
        self.assertIsNot(first.info, second.info)

    def test_observe_uses_runtime_clock_when_event_has_no_timestamp(self) -> None:
        store = InMemoryStateStore()
        runtime = AgentRuntime(store, clock=lambda: 500)
        runtime.observe(RuntimeInput("s1", "ambient"))
        self.assertEqual(store.get("s1").last_seen_at, 500)

    def test_delivery_clears_unread_and_updates_last_spoke(self) -> None:
        store = InMemoryStateStore()
        runtime = AgentRuntime(store, clock=lambda: 200)
        runtime.observe(RuntimeInput("s1", "hello", mentioned=True, unread_count=2))
        state = runtime.mark_delivered("s1")
        self.assertEqual(state.unread_count, 0)
        self.assertEqual(state.last_spoke_at, 200)
        self.assertEqual(state.reply_count, 1)

    def test_json_state_store_survives_instances(self) -> None:
        path = os.path.join(tempfile.mkdtemp(prefix="seekmem_runtime_state_"), "state.json")
        first = JsonStateStore(path)
        state = first.get("s1")
        state.quiet_until = 123
        state.unread_count = 4
        first.put(state)
        second = JsonStateStore(path)
        loaded = second.get("s1")
        self.assertEqual(loaded.quiet_until, 123)
        self.assertEqual(loaded.unread_count, 4)

    def test_runtime_package_does_not_import_astrbot(self) -> None:
        root = Path(__file__).resolve().parents[1] / "app" / "runtime"
        for path in root.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("import astrbot", text)
            self.assertNotIn("from astrbot", text)


if __name__ == "__main__":
    unittest.main()
