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
    EpisodeRecorder,
    InMemoryStateStore,
    JsonlEpisodeStore,
    RuntimeEpisode,
    ToolPolicy,
    WakeAction,
    WakeDecision,
)


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
