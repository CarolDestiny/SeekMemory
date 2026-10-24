"""Privacy regressions: pinned and designated output use the disclosure gate."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.artifact import Lineage, make, revise  # noqa: E402
from core.disclosure import RecallScene  # noqa: E402
from core.graph import Graph  # noqa: E402
from core.source import Source  # noqa: E402
from recall.pipeline import build_block  # noqa: E402
from recall.history import trajectory  # noqa: E402
from store.cache import Cache  # noqa: E402
from store.db import DB  # noqa: E402


class PrivacyOutputTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db = DB(os.path.join(tempfile.mkdtemp(prefix="seekmem_privacy_"), "t.db"))
        self.addCleanup(self.db.close)
        self.cache = Cache(self.db)
        self.graph = Graph(self.db, self.cache)
        self.config = {"bm25_enabled": False, "explore_rate": 0.0,
                       "budget_chars": 600}

    def save(self, family: str, payload: dict, *, scope: str = "shared",
             subject: str = "u1", said_by: str = "u1",
             source_umo: str = "g1") -> object:
        source = Source("s1", "turn1", source_umo, subject, "user",
                        "source text", "2026-10-22T12:00:00")
        self.db.append_sources([source])
        art = make(
            family,
            payload,
            scope=scope,
            subject_id=subject,
            said_by=said_by,
            lineage=Lineage(sources=(source.id,)),
        )
        self.db.commit(art, expected_revision=0, op="create", source_ids=(source.id,))
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
        self.assertIsNotNone(self.db.get(art.header.id))

    def test_same_session_designated_is_delivered(self):
        self.save(
            "designated",
            {"text": "designated reminder", "trigger": "reminder"},
            scope="private", subject="u1", said_by="u1", source_umo="g1",
        )
        block, _ = self.recall("g1", "reminder", "u1", private=True)
        self.assertIn("designated reminder", block)

    def test_normal_recall_does_not_consume_designated_delivery(self):
        art = self.save(
            "designated", {"text": "return the book list", "trigger": "book"},
            scope="private", source_umo="g1",
        )
        for _ in range(2):
            block, info = build_block(
                self.cache, self.graph, self.db, "g1", "book", True,
                self.config.get, "bot:FriendMessage:p1", "u1",
            )
            self.assertIn("return the book list", block)
            self.assertEqual(self.db.get(art.header.id), art)
            self.assertEqual(info["designated_ids"], (art.header.id,))
            self.assertEqual(info["designated_revisions"], {art.header.id: 1})

    def test_designated_confirmation_excludes_budget_drops_and_shadow(self):
        art = self.save(
            "designated", {"text": "private book list", "trigger": "book"},
            scope="shadow", source_umo="g1",
        )
        block, info = self.recall("g1", "book", "u1")
        self.assertNotIn("private book list", block)
        self.assertEqual(info["designated_ids"], ())
        self.config["budget_chars"] = 1
        updated = revise(art, scope="private")
        self.db.commit(updated, expected_revision=art.header.revision, op="revise")
        self.cache.put(updated)
        _, info = self.recall("g1", "book", "u1")
        self.assertNotIn(art.header.id, info["final_ids"])
        self.assertEqual(info["designated_ids"], ())

    def revised_impression(self):
        old = self.save(
            "memory", {"text": "OLD_PRIVATE_DIAGNOSIS_731", "level": "impression"},
            scope="private", source_umo="g1",
        )
        source = Source("s2", "turn2", "g2", "u1", "user", "synthetic follow-up", "t")
        self.db.append_sources([source])
        new = revise(
            old, payload={"text": "现在更愿意主动交流", "level": "impression"},
            lineage=Lineage(sources=("s1", "s2")),
        )
        self.db.commit(new, expected_revision=old.header.revision, op="revise",
                       source_ids=("s1", "s2"))
        self.cache.put(new)
        return old, new

    def test_old_impression_uses_its_own_disclosure_and_sources(self):
        old, new = self.revised_impression()
        block, info = self.recall("g2", "hello", "u1", private=False)
        self.assertEqual(info["disclosure"][new.header.id], "full")
        self.assertIn("现在更愿意主动交流", block)
        self.assertNotIn(old.payload["text"], block)
        self.assertNotIn("OLD_PRIVATE", block)

    def test_allowed_old_impression_still_has_trajectory(self):
        old, new = self.revised_impression()
        note = trajectory(self.cache, new, RecallScene("g1", "u1", "", ("u1",)))
        self.assertIn("OLD_PRIVATE", note)

    def test_history_without_disclosure_snapshot_is_not_injected(self):
        _, new = self.revised_impression()
        old_rows = [{key: value for key, value in row.items() if key != "header"}
                    for row in self.db.history(new.header.id)]
        with patch.object(self.db, "history", return_value=old_rows):
            note = trajectory(self.cache, new, RecallScene("g2", "u1"))
        self.assertEqual(note, "")
        self.assertEqual(trajectory(self.cache, new), "")
        rows = self.db.history(new.header.id)
        for row in rows:
            row["header"].pop("shareable", None)
        with patch.object(self.db, "history", return_value=rows):
            self.assertEqual(trajectory(self.cache, new, RecallScene("g1", "u1")), "")

    def test_designated_confirmation_is_explicit_and_retryable(self):
        from app.delivery import confirm_designated_delivery

        art = self.save(
            "designated", {"text": "return the book list", "trigger": "book"},
            scope="private", source_umo="g1",
        )
        self.assertEqual(confirm_designated_delivery(self.db, self.cache, ()), 0)
        with patch.object(self.db, "commit", side_effect=OSError("synthetic")):
            with self.assertRaises(OSError):
                confirm_designated_delivery(self.db, self.cache, (art.header.id,))
        self.assertEqual(self.cache.get(art.header.id), art)
        self.assertFalse(self.db.get(art.header.id).payload.get("given"))
        self.assertEqual(confirm_designated_delivery(
            self.db, self.cache, (art.header.id,), at="2026-10-24T12:00:00"), 1)
        self.assertEqual(confirm_designated_delivery(self.db, self.cache, (art.header.id,)), 0)
        self.assertEqual(self.db.get(art.header.id).header.revision, 2)

    def test_changed_designated_body_keeps_its_delivery_opportunity(self):
        from app.delivery import confirm_designated_delivery

        art = self.save(
            "designated", {"text": "old book list", "trigger": "book"},
            scope="private", source_umo="g1",
        )
        _, info = self.recall("g1", "book", "u1")
        updated = revise(art, payload={**art.payload, "text": "new book list"})
        self.db.commit(updated, expected_revision=1, op="revise")
        self.cache.put(updated)
        self.assertEqual(confirm_designated_delivery(
            self.db, self.cache, info["designated_ids"],
            expected_revisions=info["designated_revisions"]), 0)
        self.assertFalse(self.db.get(art.header.id).payload.get("given"))
        block, _ = self.recall("g1", "book", "u1")
        self.assertIn("new book list", block)


if __name__ == "__main__":
    unittest.main()
