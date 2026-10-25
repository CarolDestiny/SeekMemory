"""Reinforcement truth: final assembled IDs and cooldown accounting."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.checkpoint import CheckpointManager  # noqa: E402
from core.artifact import Strength, make  # noqa: E402
from recall.assemble import build_with_meta  # noqa: E402
from store.cache import Cache  # noqa: E402
from store import open_store  # noqa: E402


def _fact(text: str):
    return make("memory", {"text": text, "level": "fact"},
                strength=Strength(weight=1.0))


class AssemblyTruthTest(unittest.TestCase):
    def test_budget_trimming_returns_only_final_ids(self) -> None:
        first = _fact("first fact")
        second = _fact("second fact")
        text, final_ids, dropped_ids = build_with_meta(
            [first, second], budget=14,
        )
        self.assertTrue(text)
        self.assertIn(first.header.id, final_ids)
        self.assertNotIn(second.header.id, final_ids)
        self.assertIn(second.header.id, dropped_ids)

    def test_dedupe_returns_only_final_ids(self) -> None:
        first = _fact("same fact")
        second = _fact("same fact")
        _, final_ids, dropped_ids = build_with_meta([first, second], budget=100)
        self.assertEqual(final_ids, (first.header.id,))
        self.assertIn(second.header.id, dropped_ids)


class CheckpointCooldownTest(unittest.TestCase):
    def test_same_artifact_counts_once_within_cooldown(self) -> None:
        db = open_store(os.path.join(tempfile.mkdtemp(prefix="seekmem_reinforce_"), "t.db"))
        self.addCleanup(db.close)
        cache = Cache(db.artifacts)
        art = _fact("cooldown fact")
        db.artifacts.commit(art, expected_revision=0, op="create")
        cache.put(art)
        manager = CheckpointManager(db.artifacts, cache, cooldown_seconds=3600)
        self.assertTrue(manager.record(art))
        self.assertFalse(manager.record(art))
        self.assertEqual(manager.pending(), 1)
        self.assertEqual(manager.flush(), 1)
        latest = cache.get(art.header.id)
        self.assertEqual(latest.header.strength.hits, 1)

    def test_zero_cooldown_keeps_legacy_behavior(self) -> None:
        db = open_store(os.path.join(tempfile.mkdtemp(prefix="seekmem_reinforce_"), "t.db"))
        self.addCleanup(db.close)
        cache = Cache(db.artifacts)
        art = _fact("legacy fact")
        db.artifacts.commit(art, expected_revision=0, op="create")
        cache.put(art)
        manager = CheckpointManager(db.artifacts, cache, cooldown_seconds=0)
        self.assertTrue(manager.record(art))
        self.assertTrue(manager.record(art))
        self.assertEqual(manager.flush(), 1)
        self.assertEqual(cache.get(art.header.id).header.strength.hits, 2)


if __name__ == "__main__":
    unittest.main()
