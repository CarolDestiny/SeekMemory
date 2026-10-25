from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.artifact import make
from core.disclosure import (
    DisclosureLevel,
    RecallScene,
    context_affinity,
    decide,
    exposure,
    scope_prior,
)
from core.graph import Graph
from core.source import Source
from recall.pipeline import build_block
from store.cache import Cache
from store import open_store

class DisclosureShareTest(unittest.TestCase):
    def test_shared_fact_is_full_in_origin_session(self):
        art = make("memory", {"text": "owner works in Hangzhou", "level": "fact"},
                   scope="shared", subject_id="u1", said_by="u1")
        scene = RecallScene("g1", "u2", "u1", ("u2",))
        self.assertEqual(decide(art, scene, 1.0, ("g1",)).level, DisclosureLevel.FULL)

    def test_shared_fact_cross_session_stays_hint(self):
        art = make("memory", {"text": "owner works in Hangzhou", "level": "fact"},
                   scope="shared", subject_id="u1", said_by="u1")
        scene = RecallScene("g2", "u2", "u1", ("u2",))
        self.assertEqual(decide(art, scene, 1.0, ("g1",)).level, DisclosureLevel.HINT)

    def test_secret_stays_silent(self):
        art = make("secret", {"ref": "private-ref", "shadow_text": "private"},
                   scope="shared")
        scene = RecallScene("g1", "u1", "u1", ("u1",))
        self.assertEqual(decide(art, scene, 1.0, ("g1",)).level, DisclosureLevel.SILENCE)

class DisclosureFactorTest(unittest.TestCase):
    def test_scope_is_a_continuous_prior(self):
        shared = make("memory", {"text": "shared"}, scope="shared")
        private = make("memory", {"text": "private"}, scope="private")
        shadow = make("memory", {"text": "shadow"}, scope="shadow")
        self.assertGreater(scope_prior(shared), scope_prior(private))
        self.assertGreater(scope_prior(private), scope_prior(shadow))

    def test_disclosure_thresholds_remain_monotonic(self):
        art = make("memory", {"text": "shared"}, scope="shared", shareable="public")
        scene = RecallScene("g1", "u1", "u1", ("u1",))
        levels = []
        for relevance in (0.62, 0.30, 0.04, 0.03):
            levels.append(decide(art, scene, relevance, ("g1",)).level)
        self.assertEqual(levels, [
            DisclosureLevel.FULL,
            DisclosureLevel.PARAPHRASE,
            DisclosureLevel.HINT,
            DisclosureLevel.SILENCE,
        ])

    def test_origin_is_bonus_not_gate(self):
        art = make("memory", {"text": "private"}, scope="private", subject_id="u1")
        origin = RecallScene("g1", "u1", "u1", ("u1",))
        cross = RecallScene("g2", "u1", "u1", ("u1",))
        self.assertEqual(context_affinity(art, origin, ("g1",)), 1.0)
        self.assertGreater(context_affinity(art, cross, ("g1",)), 0.0)
        self.assertGreater(exposure(art, origin, 1.0, ("g1",)),
                           exposure(art, cross, 1.0, ("g1",)))


class RecallFallbackTest(unittest.TestCase):
    def setUp(self):
        self.db = open_store(os.path.join(tempfile.mkdtemp(prefix="seekmem_feel_"), "t.db"))
        self.addCleanup(self.db.close)
        self.cache = Cache(self.db.artifacts)
        self.graph = Graph(self.db, self.cache)

    def save(self, text, level, subject="u1", umo="g1"):
        source = Source("s1", "turn1", umo, subject, "user", text, "2026-10-22T12:00:00")
        self.db.sources.append_sources([source])
        art = make("memory", {"text": text, "level": level}, scope="shared",
                   subject_id=subject, said_by=subject,
                   lineage={"sources": (source.id,)})
        self.db.artifacts.commit(art, expected_revision=0, op="create", source_ids=(source.id,))
        self.cache.put(art)
        return art

    def recall(self, query, speaker="u1"):
        config = {"bm25_enabled": False, "explore_rate": 0.0}
        return build_block(self.cache, self.graph, self.db, "p1", query, True,
                           lambda key, default: config.get(key, default),
                           "p1", speaker, dry_run=True)

    def test_topic_recall_falls_back_to_recent_shared_memory(self):
        art = self.save("quarterly planning notes", "scene")
        block, info = self.recall("\u4f60\u8fd8\u8bb0\u5f97\u6211\u4eec\u5728\u7fa4\u804a\u91cc\u804a\u4e86\u5565\u5417")
        self.assertIn(art.header.id, info["picked_ids"])
        self.assertEqual(info["fallback"], "recent_topic")

    def test_profile_recall_falls_back_to_recent_fact(self):
        art = self.save("owner works in Hangzhou", "fact")
        block, info = self.recall("\u4f60\u77e5\u9053\u6211\u7684\u57fa\u7840\u4fe1\u606f\u5417")
        self.assertIn(art.header.id, info["picked_ids"])
        self.assertEqual(info["fallback"], "recent_profile")

    def test_shared_fact_is_full_in_same_group(self):
        art = self.save("owner works in Hangzhou", "fact")
        config = {"bm25_enabled": False, "explore_rate": 0.0}
        block, info = build_block(self.cache, self.graph, self.db, "g1",
                                  "owner works in Hangzhou", False,
                                  lambda key, default: config.get(key, default),
                                  "p1", "u2", dry_run=True)
        self.assertEqual(info["disclosure"][art.header.id], "full")
        self.assertIn("owner works in Hangzhou", block)


if __name__ == "__main__":
    unittest.main()
