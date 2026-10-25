"""Source-context ranking, privacy and budget regressions."""

from __future__ import annotations

import datetime
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.disclosure import DisclosureLevel, RecallScene, decide_source
from core.source import Source
from recall.source_context import RankedSource, rank_recent, render_same_session


NOW = datetime.datetime(2026, 10, 25, 12, 0, 0)


def source(source_id: str, text: str, *, session="s1", speaker="u1",
           role="user", at="2026-10-25T11:00:00") -> Source:
    return Source(source_id, f"turn-{source_id}", session, speaker, role, text, at)


class SourceRankingTest(unittest.TestCase):
    def test_lexical_match_beats_unrelated_recency(self):
        rows = [
            source("old", "quantum trading notes", at="2026-10-25T09:00:00"),
            source("new", "lunch menu", at="2026-10-25T11:59:00"),
        ]
        ranked = rank_recent(
            "quantum trading", rows, session_id="s1", speaker="u1", now=NOW
        )
        self.assertEqual(ranked[0].source.id, "old")
        self.assertGreater(ranked[0].lexical, 0)
        self.assertTrue(ranked[0].same_session)

    def test_recency_breaks_equal_lexical_ties(self):
        rows = [
            source("old", "quantum trading notes", at="2026-10-25T01:00:00"),
            source("new", "quantum trading notes", at="2026-10-25T11:00:00"),
        ]
        ranked = rank_recent(
            "quantum trading", rows, session_id="s1", speaker="u1", now=NOW
        )
        self.assertEqual(ranked[0].source.id, "new")

    def test_clock_and_empty_queries_do_not_match_source(self):
        rows = [source("s1", "quantum trading")]
        self.assertEqual(
            rank_recent("what time is it", rows, session_id="s1", now=NOW), []
        )
        self.assertEqual(
            rank_recent("\u73b0\u5728\u51e0\u70b9", rows, session_id="s1", now=NOW),
            [],
        )
        self.assertEqual(rank_recent("", rows, session_id="s1", now=NOW), [])

    def test_current_query_text_is_excluded(self):
        rows = [source("s1", "quantum trading")]
        self.assertEqual(
            rank_recent("quantum trading", rows, session_id="s1", now=NOW), []
        )

    def test_explicit_recall_can_use_recent_source_without_lexical_match(self):
        rows = [source("s1", "unrelated recent note", at="2026-10-25T11:00:00")]
        ranked = rank_recent(
            "remember what we talked about", rows, session_id="s1", now=NOW
        )
        self.assertEqual([item.source.id for item in ranked], ["s1"])


class SourcePrivacyTest(unittest.TestCase):
    def test_source_decision_keeps_cross_session_text_out(self):
        scene = RecallScene("s1", "u1")
        self.assertEqual(
            decide_source(source("same", "x", session="s1"), scene).level,
            DisclosureLevel.FULL,
        )
        self.assertEqual(
            decide_source(source("other", "x", session="s2"), scene).level,
            DisclosureLevel.HINT,
        )
        self.assertEqual(
            decide_source(source("other", "x", session="s2", speaker="u2"), scene).level,
            DisclosureLevel.SILENCE,
        )

    def test_render_only_full_same_session_sources(self):
        scene = RecallScene("s1", "u1")
        rows = [
            RankedSource(source("same", "same session phrase", session="s1"), 1, 1, True),
            RankedSource(source("other", "cross session phrase", session="s2"), 1, 1, False),
        ]
        text, used = render_same_session(rows, scene, budget_chars=100)
        self.assertIn("same session phrase", text)
        self.assertNotIn("cross session phrase", text)
        self.assertEqual(used, ("same",))

    def test_protected_source_is_never_rendered_raw(self):
        scene = RecallScene("s1", "u1")
        rows = [RankedSource(source("s1", "protected phrase"), 1, 1, True)]
        text, used = render_same_session(
            rows, scene, budget_chars=100, protected_source_ids={"s1"}
        )
        self.assertEqual(text, "")
        self.assertEqual(used, ())

    def test_render_is_bounded(self):
        scene = RecallScene("s1", "u1")
        rows = [RankedSource(source("s1", "long phrase " * 50), 1, 1, True)]
        text, _ = render_same_session(rows, scene, budget_chars=20)
        self.assertLessEqual(len(text), 20)


class RepositoryPortTest(unittest.TestCase):
    def test_recent_sources_and_artifact_lookup_are_bounded(self):
        from core.artifact import Lineage, make, revise
        from store import open_store

        db = open_store(":memory:")
        self.addCleanup(db.close)
        src = source("s1", "recent source", at="2026-10-25T11:00:00")
        db.sources.append_sources([src])
        self.assertEqual(
            [item.id for item in db.sources.recent_sources(
                since="2026-10-25T00:00:00", limit=10
            )],
            ["s1"],
        )
        art = make(
            "memory", {"text": "derived memory", "level": "fact"},
            scope="shared", subject_id="u1",
            lineage=Lineage(sources=("s1",)),
        )
        db.artifacts.commit(art, expected_revision=0, op="create", source_ids=("s1",))
        found = db.artifacts.by_source_ids(["s1"])
        self.assertEqual([item.header.id for item in found], [art.header.id])
        self.assertEqual(db.artifacts.by_source_ids([]), [])

        revised = revise(art, payload={"text": "second revision", "level": "fact"})
        db.artifacts.commit(
            revised,
            expected_revision=art.header.revision,
            op="revise",
            source_ids=("s2",),
        )
        self.assertEqual(db.artifacts.by_source_ids(["s1"]), [])
        self.assertEqual(
            [item.header.id for item in db.artifacts.by_source_ids(["s2"])],
            [art.header.id],
        )


if __name__ == "__main__":
    unittest.main()
