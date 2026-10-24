"""Privacy regressions: pinned and designated output use the disclosure gate."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.artifact import Lineage, make  # noqa: E402
from core.graph import Graph  # noqa: E402
from core.source import Source  # noqa: E402
from recall.pipeline import build_block  # noqa: E402
from store.cache import Cache  # noqa: E402
from store.db import DB  # noqa: E402


class PrivacyOutputTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db = DB(os.path.join(tempfile.mkdtemp(prefix="seekmem_privacy_"), "t.db"))
        self.addCleanup(self.db.close)
        self.cache = Cache(self.db.artifacts)
        self.graph = Graph(self.db, self.cache)
        self.config = {"bm25_enabled": False, "explore_rate": 0.0,
                       "budget_chars": 600}

    def save(self, family: str, payload: dict, *, scope: str = "shared",
             subject: str = "u1", said_by: str = "u1",
             source_umo: str = "g1") -> object:
        source = Source("s1", "turn1", source_umo, subject, "user",
                        "source text", "2026-10-22T12:00:00")
        self.db.sources.append_sources([source])
        art = make(
            family,
            payload,
            scope=scope,
            subject_id=subject,
            said_by=said_by,
            lineage=Lineage(sources=(source.id,)),
        )
        self.db.artifacts.commit(art, expected_revision=0, op="create", source_ids=(source.id,))
        self.cache.put(art)
        return art

    def recall(self, umo: str, text: str, speaker: str, *, private: bool = True):
        return build_block(
            self.cache, self.graph, self.db, umo, text, private,
            self.config.get, "bot:FriendMessage:p1", speaker, dry_run=True,
        )

    def test_pinned_shared_impression_does_not_leak_raw_text_cross_session(self):
        art = self.save(
            "memory",
            {"text": "pinned secret phrase", "level": "impression"},
            scope="shared", subject="u1", said_by="u1", source_umo="g1",
        )
        block, info = self.recall("g2", "hello", "u1", private=False)
        self.assertNotIn("pinned secret phrase", block)
        self.assertNotEqual(info["disclosure"].get(art.header.id), "full")
        self.assertIn(art.header.id, info["pinned_ids"])

    def test_unverified_persona_cannot_bypass_disclosure(self):
        art = self.save(
            "persona", {"text": "global persona phrase"},
            scope="shared", subject="bot:self", said_by="inferred",
            source_umo="g1",
        )
        block, info = self.recall("g2", "hello", "u1", private=False)
        # #15：任意旧人格文字不再自动获得全局全文许可。
        self.assertNotIn("global persona phrase", block)
        self.assertEqual(info["disclosure"].get(art.header.id), "silence")

    def test_cross_session_designated_is_not_delivered(self):
        art = self.save(
            "designated",
            {"text": "designated secret", "trigger": "secret"},
            scope="shared", subject="u1", said_by="u1", source_umo="g1",
        )
        block, _ = self.recall("g2", "secret", "u2", private=True)
        self.assertNotIn("designated secret", block)
        self.assertIsNotNone(self.db.artifacts.get(art.header.id))

    def test_same_session_designated_is_delivered(self):
        self.save(
            "designated",
            {"text": "designated reminder", "trigger": "reminder"},
            scope="private", subject="u1", said_by="u1", source_umo="g1",
        )
        block, _ = self.recall("g1", "reminder", "u1", private=True)
        self.assertIn("designated reminder", block)


if __name__ == "__main__":
    unittest.main()
