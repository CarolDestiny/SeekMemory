from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.artifact import make
from core.graph import Graph
from core.source import Source
from recall.pipeline import build_block
from store.cache import Cache
from store.db import DB


class PipelineDisclosureTest(unittest.TestCase):
    def test_cross_session_shared_memory_is_paraphrased(self):
        db = DB(os.path.join(tempfile.mkdtemp(), "t.db"))
        cache = Cache(db)
        graph = Graph(db, cache)
        src = Source("s1", "turn1", "s1", "u1", "user", "source text", "t")
        db.append_sources([src])
        art = make("memory", {"text": "top secret phrase", "level": "scene",
                              "tags": "project"}, subject_id="u1", scope="shared")
        db.commit(art, expected_revision=0, op="create", source_ids=("s1",))
        cache.put(art)
        block, info = build_block(cache, graph, db, "s2", "top secret phrase",
                                  True, lambda _k, default: default,
                                  "napcat:FriendMessage:u1", "u1")
        self.assertTrue(block)
        self.assertNotIn("top secret phrase", block)
        self.assertEqual(info["disclosure"][art.header.id], "paraphrase")


if __name__ == "__main__":
    unittest.main()
