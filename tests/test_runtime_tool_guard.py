"""Tool guard and episode-outcome contract tests."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.runtime import (  # noqa: E402
    ToolCall,
    ToolPolicy,
    delivery_failure_metadata,
    episode_outcome,
    normalize_tool_calls,
    safe_error_code,
)
from app.runtime.tools import trace_tool_call  # noqa: E402


class Tool:
    def __init__(self, name: str) -> None:
        self.name = name


class ToolSet:
    def __init__(self, *names: str) -> None:
        self.tools = [Tool(name) for name in names]

    def remove_tool(self, name: str) -> None:
        self.tools = [tool for tool in self.tools if tool.name != name]


class Event:
    def __init__(self) -> None:
        self.extras = {}

    def get_extra(self, key, default=None):
        return self.extras.get(key, default)

    def set_extra(self, key, value):
        self.extras[key] = value


class ToolGuardTest(unittest.TestCase):
    def test_policy_filter_is_a_real_pre_dispatch_guard(self) -> None:
        policy = ToolPolicy(("memory_",))
        tool_set = ToolSet("memory_search", "shell", "memory_write")
        removed = policy.filter_tool_set(tool_set)
        self.assertEqual(removed, ("shell",))
        self.assertEqual([tool.name for tool in tool_set.tools], [
            "memory_search", "memory_write",
        ])
        self.assertTrue(policy.check_tool("memory_search", {}).enforced)
        self.assertFalse(policy.check_tool("shell", {}).allowed)

    def test_malformed_tool_set_is_fail_open(self) -> None:
        policy = ToolPolicy(("memory_",))
        class BadToolSet:
            tools = [Tool("shell")]
        self.assertEqual(policy.filter_tool_set(BadToolSet()), ())
        self.assertEqual(policy.filter_tool_set(None), ())

    def test_observation_policy_never_claims_enforcement(self) -> None:
        event = Event()
        call = trace_tool_call(
            event, "shell", {"command": "do not persist"}, ToolPolicy(("memory_",))
        )
        self.assertFalse(call.allowed)
        self.assertFalse(call.enforced)
        self.assertTrue(call.advisory)
        self.assertFalse(event.extras["_seekmemory_tool_policy_enforced"])
        self.assertEqual(
            event.extras["_seekmemory_tool_policy_mismatches"], ("shell",)
        )

    def test_tool_result_failure_is_metadata_only(self) -> None:
        from app.runtime import tool_result_failed

        class Result:
            isError = True
            content = "sensitive tool output"

        self.assertTrue(tool_result_failed(Result()))
        self.assertFalse(tool_result_failed(None))


class EpisodeOutcomeTest(unittest.TestCase):
    def test_tool_error_keeps_names_but_not_arguments(self) -> None:
        call = ToolCall("shell", False, ("command",), enforced=False)
        result = episode_outcome(
            delivered=True,
            tool_calls=(call,),
            tool_failed=True,
            error=RuntimeError("secret user text /home/private"),
        )
        self.assertEqual(result.outcome, "tool_error")
        self.assertEqual(result.error, "RuntimeError")
        self.assertEqual(result.tool_calls, ("shell",))
        self.assertNotIn("secret", repr(result.fields()))
        self.assertEqual(normalize_tool_calls([call]), ("shell",))

    def test_delivery_failure_takes_precedence(self) -> None:
        result = episode_outcome(
            delivered=False,
            tool_calls=("memory_search",),
            tool_failed=True,
            error="delivery_failed",
        )
        self.assertEqual(result.outcome, "delivery_failed")
        self.assertFalse(result.delivered)
        self.assertEqual(result.error, "delivery_failed")

    def test_error_codes_are_bounded_and_body_free(self) -> None:
        self.assertEqual(safe_error_code(RuntimeError("secret")), "RuntimeError")
        self.assertEqual(safe_error_code("tool.timeout"), "tool.timeout")
        self.assertEqual(safe_error_code("secret user text"), "error")
        metadata = delivery_failure_metadata(RuntimeError("secret"))
        self.assertEqual(metadata["outcome"], "delivery_failed")
        self.assertNotIn("secret", repr(metadata))


if __name__ == "__main__":
    unittest.main()
