"""Identity isolation regressions: subject, scope, source id and merge boundaries."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.contracts import DialogueTurn  # noqa: E402
from core.artifact import Strength, make  # noqa: E402
from core.graph import Graph  # noqa: E402
from core.source import make_source_id  # noqa: E402
from maintain.impression import revise_impression  # noqa: E402
from maintain.merge import merge_similar  # noqa: E402
from perceive.absorb import absorb, existing_texts_by_subject  # noqa: E402
from perceive.extract import filter_duplicates  # noqa: E402
from store.cache import Cache  # noqa: E402
from store import open_store  # noqa: E402


class FakeProvider:
    def __init__(self, text: str) -> None:
        self.text = text

    async def text_chat(self, system_prompt: str = "", prompt: str = ""):
        class Resp:
            completion_text = self.text

        return Resp()


def _turn(text: str, session: str = "umo:a", speaker: str = "10001") -> DialogueTurn:
    return DialogueTurn(session, speaker, "user", text, "2026-10-22T12:00:00", "s1")


def _db():
    path = os.path.join(tempfile.mkdtemp(prefix="seekmem_identity_"), "t.db")
    db = open_store(path)
    return db, Cache(db.artifacts), Graph(db.artifacts)


class SourceIdentityTest(unittest.TestCase):
    def test_event_id_is_scoped_by_session_speaker_and_text(self) -> None:
        base = dict(event_id="m-1", speaker_id="u1", role="user", text="same", at="t")
        self.assertNotEqual(
            make_source_id(session_id="friend:a", **base),
            make_source_id(session_id="group:b", **base),
        )
        self.assertNotEqual(
            make_source_id(session_id="friend:a", **base),
            make_source_id(session_id="friend:a", **{**base, "text": "different"}),
        )

    def test_same_delivery_is_idempotent(self) -> None:
        args = dict(
            event_id="m-1", session_id="friend:a", speaker_id="u1",
            role="user", text="same", at="t",
        )
        self.assertEqual(make_source_id(**args), make_source_id(**args))
        self.assertEqual(
            make_source_id(**args),
            make_source_id(**{**args, "at": "later"}),
        )


class DedupeBoundaryTest(unittest.TestCase):
    def test_same_text_from_two_subjects_survives_both(self) -> None:
        existing = {"private\x1fu0": ["I live in Hangzhou"]}
        items = [
            {"text": "I live in Hangzhou", "subject_id": "u1"},
            {"text": "I live in Hangzhou", "subject_id": "u2"},
        ]
        kept = filter_duplicates(
            items,
            existing_by_subject=existing,
            subject_of=lambda item: f"private\x1f{item['subject_id']}",
        )
        self.assertEqual(len(kept), 2)

    def test_same_subject_still_deduplicates_repeated_text(self) -> None:
        items = [
            {"text": "I live in Hangzhou", "subject_id": "u1"},
            {"text": "I live in Hangzhou", "subject_id": "u1"},
        ]
        kept = filter_duplicates(
            items,
            existing_by_subject={},
            subject_of=lambda item: f"private\x1f{item['subject_id']}",
        )
        self.assertEqual(len(kept), 1)


class AbsorbIsolationTest(unittest.TestCase):
    def test_two_speakers_saying_same_sentence_both_persist(self) -> None:
        db, cache, graph = _db()
        raw = json.dumps([{"level": "fact", "text": "I live in Hangzhou"}])
        one = asyncio.run(absorb(
            [_turn("I live in Hangzhou", "umo:a", "10001")], db.artifacts, db.sources, cache, graph,
            FakeProvider(raw),
        ))
        two = asyncio.run(absorb(
            [_turn("I live in Hangzhou", "umo:b", "10002")], db.artifacts, db.sources, cache, graph,
            FakeProvider(raw),
        ))
        self.assertEqual(one.written, 1)
        self.assertEqual(two.written, 1)
        self.assertEqual(len(cache.active("memory")), 2)
        subjects = {art.header.subject_id for art in cache.active("memory")}
        self.assertEqual(subjects, {"10001", "10002"})

    def test_existing_texts_are_grouped_by_subject_and_scope(self) -> None:
        db, cache, _ = _db()
        art = make(
            "memory", {"text": "same", "level": "fact"},
            scope="private", subject_id="10001",
        )
        db.artifacts.commit(art, expected_revision=0, op="create")
        cache.put(art)
        grouped = existing_texts_by_subject(cache)
        self.assertIn("private\x1f10001", grouped)
        self.assertIn("same", grouped["private\x1f10001"])


class ImpressionIsolationTest(unittest.TestCase):
    def test_similar_impressions_from_different_subjects_do_not_revise(self) -> None:
        db, cache, _ = _db()
        old = make(
            "memory", {"text": "he is stubborn but helps when it matters",
                       "level": "impression"},
            strength=Strength(weight=1.5), scope="private", subject_id="10001",
        )
        db.artifacts.commit(old, expected_revision=0, op="create")
        cache.put(old)
        new = make(
            "memory", {"text": "he is stubborn but helps when it really matters",
                       "level": "impression"},
            strength=Strength(weight=1.6), scope="private", subject_id="10002",
        )
        self.assertIsNone(revise_impression(db.artifacts, cache, new))
        self.assertEqual(cache.get(old.header.id).header.revision, 1)
        self.assertIsNone(cache.get(new.header.id))


class MergeIsolationTest(unittest.TestCase):
    def test_merge_does_not_cross_subjects(self) -> None:
        db, cache, _ = _db()
        for subject in ("u1", "u2"):
            for index in range(300):
                art = make(
                    "memory",
                    {"text": "he works late again today", "level": "scene"},
                    strength=Strength(weight=1.0),
                    scope="private",
                    subject_id=subject,
                    time={"created": "2024-01-01T00:00:00",
                          "updated": "2024-01-01T00:00:00"},
                )
                db.artifacts.upsert(art)
                cache.put(art)
        made = merge_similar(db.artifacts, cache, limit=50)
        self.assertGreaterEqual(made, 2)
        impressions = cache.by_level("impression")
        self.assertEqual(len(impressions), 2)
        self.assertEqual({art.header.subject_id for art in impressions}, {"u1", "u2"})


if __name__ == "__main__":
    unittest.main()
