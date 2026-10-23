"""Temporal validity and relative query window regressions."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.artifact import Lineage, TimeSpan, make  # noqa: E402
from core.graph import Graph  # noqa: E402
from core.source import Source  # noqa: E402
from recall.pipeline import build_block  # noqa: E402
from recall.temporal import in_window, query_window, valid_at  # noqa: E402
from store.cache import Cache  # noqa: E402
from store.db import DB  # noqa: E402


class TemporalPolicyTest(unittest.TestCase):
    def test_validity_bounds_and_expiry(self) -> None:
        today = date(2026, 10, 21)
        self.assertFalse(valid_at(
            make("memory", {"text": "future", "level": "fact"},
                 time=TimeSpan(valid_from="2026-10-22")), today))
        self.assertFalse(valid_at(
            make("memory", {"text": "old", "level": "fact"},
                 time=TimeSpan(valid_to="2026-10-20")), today))
        self.assertFalse(valid_at(
            make("memory", {"text": "expired", "level": "fact"},
                 time=TimeSpan(expires="2026-10-20")), today))
        self.assertTrue(valid_at(
            make("memory", {"text": "current", "level": "fact"},
                 time=TimeSpan(valid_from="2026-10-20", valid_to="2026-10-21")),
            today))

    def test_relative_windows(self) -> None:
        today = date(2026, 10, 21)
        self.assertEqual(query_window("\u4eca\u5929", today), (today, today))
        self.assertEqual(query_window("\u4e0b\u5468", today),
                         (date(2026, 10, 26), date(2026, 11, 1)))
        self.assertEqual(query_window("\u4e0b\u4e2a\u6708", today),
                         (date(2026, 11, 1), date(2026, 11, 30)))
        self.assertIsNone(query_window("ordinary question", today))

    def test_window_uses_event_date(self) -> None:
        art = make("memory", {"text": "next week plan", "level": "fact"},
                   time=TimeSpan(created="2026-10-27"))
        self.assertTrue(in_window(art, (date(2026, 10, 26), date(2026, 11, 1))))
        self.assertFalse(in_window(art, (date(2026, 10, 19), date(2026, 10, 25))))


class TemporalRecallTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db = DB(os.path.join(tempfile.mkdtemp(prefix="seekmem_time_"), "t.db"))
        self.addCleanup(self.db.close)
        self.cache = Cache(self.db)
        self.graph = Graph(self.db, self.cache)
        self.config = {"bm25_enabled": False, "explore_rate": 0.0,
                       "budget_chars": 600}

    def save(self, text: str, **time_kw) -> object:
        self.db.append_sources([
            Source("s1", "t1", "g1", "u1", "user", text, "2026-01-01T00:00:00")
        ])
        art = make(
            "memory", {"text": text, "level": "fact"},
            scope="shared", subject_id="u1",
            lineage=Lineage(sources=("s1",)),
            time=TimeSpan(**time_kw),
        )
        self.db.commit(art, expected_revision=0, op="create", source_ids=("s1",))
        self.cache.put(art)
        return art

    def recall(self, text: str):
        return build_block(
            self.cache, self.graph, self.db, "g1", text, True,
            self.config.get, "bot:FriendMessage:p1", "u1", dry_run=True,
        )

    def test_expired_memory_is_not_recalled(self) -> None:
        self.save("expired phrase", created="2020-01-01", valid_to="2020-01-02")
        block, info = self.recall("\u4f60\u8fd8\u8bb0\u5f97 expired phrase \u5417")
        self.assertEqual(block, "")
        self.assertEqual(info["picked_ids"], ())

    def test_future_memory_is_not_recalled(self) -> None:
        self.save("future phrase", created="2999-01-01", valid_from="2999-01-01")
        block, info = self.recall("\u4f60\u8fd8\u8bb0\u5f97 future phrase \u5417")
        self.assertEqual(block, "")
        self.assertEqual(info["picked_ids"], ())

    def test_current_memory_is_recalled(self) -> None:
        art = self.save("current phrase", created="2026-01-01")
        block, info = self.recall("\u4f60\u8fd8\u8bb0\u5f97 current phrase \u5417")
        self.assertIn(art.header.id, info["picked_ids"])
        self.assertIn("current phrase", block)


if __name__ == "__main__":
    unittest.main()
