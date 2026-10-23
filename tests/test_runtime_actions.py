"""Runtime action, episode, tool policy and LLM gate tests."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adapters.astrbot_actions import AstrBotActionPort  # noqa: E402
from adapters.astrbot_runtime import AstrBotRuntimeAdapter  # noqa: E402
from app.runtime import (  # noqa: E402
    AgentRuntime,
    DBEpisodeStore,
    DBStateStore,
    EpisodeRecorder,
    InMemoryStateStore,
    JsonlEpisodeStore,
    RuntimeEpisode,
    ToolPolicy,
    WakeAction,
    WakeDecision,
)
from store.db import DB  # noqa: E402


class Context:
    def __init__(self) -> None:
        self.sent = []

    async def send_message(self, session, chain):
        self.sent.append((session, chain))


class Event:
    def __init__(self) -> None:
        self.extras = {}
        self.call_llm = True

    def set_extra(self, key, value):
        self.extras[key] = value

    def get_extra(self, key, default=None):
        return self.extras.get(key, default)

    def should_call_llm(self, value):
        self.call_llm = value


class ActionTest(unittest.TestCase):
    def test_send_proactive_and_wait(self) -> None:
        context = Context()
        actions = AstrBotActionPort(context, message_factory=lambda text: text)
        asyncio.run(actions.send("s1", "hello"))
        asyncio.run(actions.proactive("s1", "later"))
        asyncio.run(actions.wait(0))
        self.assertEqual(context.sent, [("s1", "hello"), ("s1", "later")])

    def test_runtime_quiet_window(self) -> None:
        store = InMemoryStateStore()
        runtime = AgentRuntime(store, clock=lambda: 100)
        state = runtime.quiet("s1", 30)
        self.assertEqual(state.quiet_until, 130)

    def test_llm_gate_is_opt_in(self) -> None:
        event = Event()
        decision = WakeDecision(WakeAction.OBSERVE, "ambient")
        AstrBotRuntimeAdapter.apply_llm_gate(event, decision, False)
        self.assertTrue(event.call_llm)
        AstrBotRuntimeAdapter.apply_llm_gate(event, decision, True)
        self.assertFalse(event.call_llm)

    def test_tool_policy_and_trace(self) -> None:
        event = Event()
        policy = ToolPolicy(("memory_",))
        call = AstrBotRuntimeAdapter.observe_tool(
            event, "memory_search", {"query": "x"}, policy
        )
        self.assertTrue(call.allowed)
        self.assertEqual(event.extras["_seekmemory_tool_calls"], ("memory_search",))
        blocked = AstrBotRuntimeAdapter.observe_tool(event, "shell", {}, policy)
        self.assertFalse(blocked.allowed)

    def test_db_state_and_episode_stores(self) -> None:
        db = DB(os.path.join(tempfile.mkdtemp(prefix="seekmem_runtime_db_"), "memory.db"))
        state_store = DBStateStore(db)
        state = state_store.get("s1")
        state.quiet_until = 321
        state_store.put(state)
        self.assertEqual(DBStateStore(db).get("s1").quiet_until, 321)
        self.assertEqual(db.list_runtime_state_sessions(), ["s1"])

        recorder = EpisodeRecorder(DBEpisodeStore(db))
        recorder.record(RuntimeEpisode(
            session_id="s1", at="2026-01-01T00:00:00", decision="reply",
            reason="mention", action="reply", delivered=True,
            response_chars=4, tool_calls=("memory_search",), outcome="ok",
            user_source_id="u1", assistant_source_id="a1",
        ))
        rows = db.list_runtime_episodes("s1")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["decision"], "reply")
        self.assertIn("memory_search", rows[0]["tool_calls"])

    def test_db_episode_pruning_and_fail_open(self) -> None:
        db = DB(os.path.join(tempfile.mkdtemp(prefix="seekmem_runtime_prune_"), "memory.db"))
        recorder = EpisodeRecorder(DBEpisodeStore(db))
        for i in range(3):
            recorder.record(RuntimeEpisode(
                session_id="s1", at=f"2026-01-0{i + 1}T00:00:00",
                decision="observe", reason="ambient", action="reply",
                delivered=True, outcome="ok",
            ))
        self.assertGreaterEqual(db.prune_runtime_episodes(retention_days=0, max_rows=2), 1)
        self.assertEqual(len(db.list_runtime_episodes("s1")), 2)

        class BrokenDB:
            def get_runtime_state(self, session_id):
                raise RuntimeError("busy")

            def put_runtime_state(self, session_id, payload):
                raise RuntimeError("busy")

            def append_runtime_episode(self, payload):
                raise RuntimeError("busy")

        broken = BrokenDB()
        state_store = DBStateStore(broken)
        self.assertEqual(state_store.get("s1").session_id, "s1")
        state_store.put(state_store.get("s1"))
        self.assertEqual(state_store.last_error, "RuntimeError")
        episode_store = DBEpisodeStore(broken)
        episode_store.append(RuntimeEpisode(session_id="s1", at="t", decision="x",
                                           reason="y", action="z", delivered=False))
        self.assertEqual(episode_store.last_error, "RuntimeError")

    def test_episode_jsonl_has_no_message_body(self) -> None:
        path = os.path.join(tempfile.mkdtemp(prefix="seekmem_episode_"), "episodes.jsonl")
        recorder = EpisodeRecorder(JsonlEpisodeStore(path))
        recorder.record(RuntimeEpisode(
            session_id="s1", at="t", decision="reply", reason="mention",
            action="reply", delivered=True, response_chars=3, outcome="ok",
            user_source_id="u1", assistant_source_id="a1",
        ))
        with open(path, encoding="utf-8") as handle:
            row = json.loads(handle.read())
        self.assertNotIn("text", row)
        self.assertEqual(row["response_chars"], 3)


if __name__ == "__main__":
    unittest.main()
