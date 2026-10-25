"""End-to-end continuity: extraction, storage, recall and correction."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.contracts import DialogueTurn  # noqa: E402
from core.artifact import Lineage, Strength, TimeSpan, make, revise  # noqa: E402
from recall.temporal import valid_at  # noqa: E402
from core.graph import Graph  # noqa: E402
from core.source import Source  # noqa: E402
from perceive.absorb import absorb  # noqa: E402
from recall.pipeline import build_block  # noqa: E402
from recall.retriever import HybridRetriever  # noqa: E402
from store.cache import Cache  # noqa: E402
from store import open_store  # noqa: E402


class Provider:
    def __init__(self, text: str) -> None:
        self.text = text

    async def text_chat(self, system_prompt: str = "", prompt: str = ""):
        class Resp:
            completion_text = self.text

        return Resp()


class ContinuityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db = open_store(os.path.join(tempfile.mkdtemp(prefix="seekmem_continuity_"), "t.db"))
        self.addCleanup(self.db.close)
        self.cache = Cache(self.db.artifacts)
        self.graph = Graph(self.db, self.cache)
        self.retriever = HybridRetriever(self.graph, self.cache)
        self.session = "bot:FriendMessage:p1"
        self.owner = "bot:FriendMessage:p1"

    def extract(self, text: str, model_text: str):
        source = Source("s1", "turn1", self.session, "u1", "user",
                        text, "2026-10-22T12:00:00")
        self.db.sources.append_sources([source])
        outcome = asyncio.run(absorb(
            [DialogueTurn(self.session, "u1", "user", text,
                          "2026-10-22T12:00:00", "s1")],
            self.db, self.cache, self.graph, Provider(model_text),
        ))
        self.assertEqual(outcome.written, 1)
        return self.cache.active("memory")[0]

    def recall(self, query: str) -> tuple[str, dict]:
        return build_block(
            self.cache, self.graph, self.db, self.session, query, True,
            {"bm25_enabled": True, "explore_rate": 0.0}.get,
            self.owner, "u1", dry_run=True, hybrid_retriever=self.retriever,
        )

    def test_supersedes_expires_the_old_fact(self) -> None:
        old = make(
            "memory", {"text": "The owner lives in Hangzhou", "level": "fact"},
            scope="private", subject_id="u1", strength=Strength(weight=1.0),
            lineage=Lineage(sources=("s1",)),
        )
        self.db.artifacts.commit(old, expected_revision=0, op="create")
        self.cache.put(old)
        outcome = asyncio.run(absorb(
            [DialogueTurn(self.session, "u1", "user", "I moved to Shanghai",
                          "2026-10-22T12:00:00", "s1")],
            self.db, self.cache, self.graph,
            Provider(json.dumps([{
                "level": "fact",
                "text": "The owner lives in Shanghai",
                "subject_kind": "speaker",
                "subject_id": "u1",
                "supersedes": "The owner lives in Hangzhou",
            }])),
        ))
        self.assertEqual(outcome.written, 1)
        expired = self.cache.get(old.header.id)
        self.assertIsNotNone(expired)
        self.assertIsNotNone(expired.header.time.valid_to)
        self.assertFalse(valid_at(expired))

    def test_correction_revises_the_current_answer(self) -> None:
        original = self.extract(
            "I live in Hangzhou",
            json.dumps([{"level": "fact", "text": "The owner lives in Hangzhou",
                         "subject_kind": "speaker", "subject_id": "u1"}]),
        )
        block, info = self.recall("Where does the owner live?")
        self.assertIn(original.header.id, info["picked_ids"])
        self.assertIn("Hangzhou", block)

        corrected = revise(
            original,
            {"text": "The owner lives in Shanghai", "level": "fact"},
            time=TimeSpan(created=original.header.time.created,
                          updated=original.header.time.updated),
        )
        self.db.artifacts.commit(corrected, expected_revision=1, op="revise")
        self.cache.put(corrected)
        block, info = self.recall("Where does the owner live?")
        self.assertIn(corrected.header.id, info["picked_ids"])
        self.assertIn("Shanghai", block)
        self.assertNotIn("Hangzhou", block)


if __name__ == "__main__":
    unittest.main()
