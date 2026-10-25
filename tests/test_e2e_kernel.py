from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.checkpoint import CheckpointManager
from app.contracts import ChatResponse, DialogueTurn
from core.artifact import content_of
from core.disclosure import DisclosureLevel, RecallScene, decide
from core.graph import Graph
from core.source import Source
from perceive.absorb import absorb
from store.cache import Cache
from store import open_store


GOOD = json.dumps([
    {"level": "fact", "text": "The owner is preparing a job interview",
     "tags": "job interview", "about": "other", "subject_id": "u1",
     "arousal": 0.4, "valence": 0.2, "funny": 0.0}
])


class FakeChatModel:
    async def complete(self, request):
        return ChatResponse(text=GOOD, model="fake", provider_id="fake")


class KernelEndToEndTest(unittest.TestCase):
    def test_source_to_artifact_to_disclosure_to_checkpoint(self):
        db = open_store(os.path.join(tempfile.mkdtemp(), "t.db"))
        cache = Cache(db.artifacts)
        graph = Graph(db, cache)
        user = Source("s_user", "turn1", "umo1", "u1", "user", "I have an interview", "t1")
        bot = Source("s_bot", "turn1", "umo1", "bot", "assistant", "good luck", "t2", reply_to="s_user")
        self.assertEqual(db.sources.append_sources([user, bot]), 2)
        written = asyncio.run(absorb([DialogueTurn("umo1", "u1", "user", "I have an interview", "", "s_user")],
                                      db, cache, graph, FakeChatModel()))
        self.assertEqual(written.written, 1)
        arts = cache.active("memory")
        self.assertEqual(len(arts), 1)
        art = arts[0]
        self.assertEqual(art.header.subject_id, "u1")
        self.assertEqual(art.header.lineage.sources, ("s_user",))
        self.assertEqual(db.artifacts.history(art.header.id)[0]["op"], "create")
        self.assertEqual(content_of(art), "The owner is preparing a job interview")
        scene = RecallScene("umo1", "u1", "u1", ("u1",))
        decision = decide(art, scene, 1.0, origin_sessions=("umo1",))
        self.assertEqual(decision.level, DisclosureLevel.FULL)
        mgr = CheckpointManager(db.artifacts, cache)
        mgr.record(art)
        self.assertEqual(mgr.flush(), 1)
        latest = cache.get(art.header.id)
        self.assertEqual(latest.header.revision, 2)
        self.assertEqual(latest.header.strength.hits, 1)


if __name__ == "__main__":
    unittest.main()
