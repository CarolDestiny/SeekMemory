"""Round-robin topic batch selection tests."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.contracts import DialogueTurn  # noqa: E402
from app.flush_policy import (  # noqa: E402
    pack_same_session_batches,
    select_topic_batches,
)


def turn(session: str, topic: str, text: str = "hello") -> DialogueTurn:
    return DialogueTurn(session, "u", "user", text, "", "", topic)


class RoundRobinTest(unittest.TestCase):
    def test_single_long_session_cannot_take_every_slot(self) -> None:
        items = [turn("a", "t1"), turn("a", "t1"), turn("a", "t2"), turn("b", "t3")]
        batches = select_topic_batches(items, 2)
        self.assertEqual([(session, topic) for session, topic, _ in batches],
                         [("a", "t1"), ("b", "t3")])

    def test_sessions_rotate_until_cap(self) -> None:
        items = [turn("a", "t1"), turn("b", "t2"), turn("c", "t3"), turn("a", "t4")]
        self.assertEqual(
            [(session, topic) for session, topic, _ in select_topic_batches(items, 4)],
            [("a", "t1"), ("b", "t2"), ("c", "t3"), ("a", "t4")],
        )

    def test_cap_limits_batches(self) -> None:
        items = [turn("a", "t1"), turn("b", "t2"), turn("c", "t3")]
        self.assertEqual(len(select_topic_batches(items, 2)), 2)
        self.assertEqual(len(select_topic_batches(items, 99)), 3)

    def test_empty_input_returns_no_batches(self) -> None:
        self.assertEqual(select_topic_batches([], 3), [])


class SameSessionPackingTest(unittest.TestCase):
    def test_same_session_topics_pack_into_one_batch(self) -> None:
        units = [
            ("s", "t1", [turn("s", "t1", "a")]),
            ("s", "t2", [turn("s", "t2", "b")]),
        ]
        batches = pack_same_session_batches(units, token_limit=1000)
        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0].topics, ("t1", "t2"))
        self.assertEqual([row.text for row in batches[0].rows], ["a", "b"])

    def test_different_sessions_never_pack_together(self) -> None:
        units = [
            ("a", "t1", [turn("a", "t1", "a")]),
            ("b", "t2", [turn("b", "t2", "b")]),
        ]
        batches = pack_same_session_batches(units, token_limit=1000)
        self.assertEqual([batch.session_id for batch in batches], ["a", "b"])

    def test_interleaved_sessions_group_by_first_seen_session(self) -> None:
        units = [
            ("a", "t1", [turn("a", "t1", "a1")]),
            ("b", "t1", [turn("b", "t1", "b1")]),
            ("a", "t2", [turn("a", "t2", "a2")]),
        ]
        batches = pack_same_session_batches(units, token_limit=1000)
        self.assertEqual(len(batches), 2)
        by_session = {batch.session_id: batch for batch in batches}
        self.assertEqual(by_session["a"].topics, ("t1", "t2"))
        self.assertEqual([row.text for row in by_session["a"].rows], ["a1", "a2"])
        self.assertEqual(by_session["b"].topics, ("t1",))
        self.assertEqual([row.text for row in by_session["b"].rows], ["b1"])

    def test_token_limit_splits_and_oversized_unit_stays_whole(self) -> None:
        units = [
            ("s", "t1", [turn("s", "t1", "x" * 100)]),
            ("s", "t2", [turn("s", "t2", "y" * 100)]),
            ("s", "t3", [turn("s", "t3", "z" * 100)]),
        ]
        batches = pack_same_session_batches(units, token_limit=10)
        self.assertEqual([batch.topics for batch in batches],
                         [("t1",), ("t2",), ("t3",)])
        self.assertTrue(all(len(batch.rows) == 1 for batch in batches))


if __name__ == "__main__":
    unittest.main()
