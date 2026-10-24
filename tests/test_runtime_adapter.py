"""AstrBot runtime adapter tests without importing AstrBot."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adapters.astrbot_runtime import AstrBotRuntimeAdapter  # noqa: E402
from app.runtime import WakeAction, RunDecision  # noqa: E402


class Event:
    def __init__(self, private: bool) -> None:
        self.private = private
        self.extras = {}
        self.created_at = 0.0

    def is_private_chat(self) -> bool:
        return self.private

    def set_extra(self, key, value) -> None:
        self.extras[key] = value


class AdapterTest(unittest.TestCase):
    def test_private_event_maps_to_direct_input(self) -> None:
        result = AstrBotRuntimeAdapter.from_event(
            Event(True), "hello?", "s1", "u1", unread_count=3
        )
        self.assertTrue(result.private)
        self.assertTrue(result.mentioned)
        self.assertTrue(result.question)
        self.assertEqual(result.unread_count, 3)

    def test_event_timestamp_and_unread_watermark_are_mapped(self) -> None:
        event = Event(False)
        event.created_at = 123.5
        result = AstrBotRuntimeAdapter.from_event(
            event, "ambient", "g1", "u1", unread_count=4, unread_seq=9
        )
        self.assertEqual(result.at, 123.5)
        self.assertEqual(result.unread_count, 4)
        self.assertEqual(result.unread_seq, 9)

    def test_invalid_timestamp_and_negative_watermarks_are_clamped(self) -> None:
        event = Event(False)
        event.created_at = "not-a-timestamp"
        result = AstrBotRuntimeAdapter.from_event(
            event, "ambient", "g1", "u1", unread_count=-3, unread_seq=-2
        )
        self.assertEqual(result.at, 0.0)
        self.assertEqual(result.unread_count, 0)
        self.assertEqual(result.unread_seq, 0)

    def test_group_event_is_not_direct(self) -> None:
        result = AstrBotRuntimeAdapter.from_event(
            Event(False), "ambient", "g1", "u1"
        )
        self.assertFalse(result.private)
        self.assertFalse(result.mentioned)
        self.assertFalse(result.question)

    def test_wake_command_marks_group_message_as_direct(self) -> None:
        event = Event(False)
        event.is_at_or_wake_command = True
        result = AstrBotRuntimeAdapter.from_event(event, "hello", "g1", "u1")
        self.assertTrue(result.mentioned)

    def test_decision_is_exposed_as_event_metadata(self) -> None:
        event = Event(False)
        AstrBotRuntimeAdapter.apply_decision(
            event, RunDecision(WakeAction.OBSERVE, "ambient_message")
        )
        self.assertEqual(event.extras["_seekmemory_runtime_action"], "observe")
        self.assertEqual(event.extras["_seekmemory_runtime_reason"], "ambient_message")


if __name__ == "__main__":
    unittest.main()
