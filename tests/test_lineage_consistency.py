"""Lineage and cache consistency regressions for impression revision."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.artifact import Lineage, Strength, content_of, make  # noqa: E402
from maintain.impression import _retire, revise_impression  # noqa: E402
from store.cache import Cache  # noqa: E402
from store import open_store  # noqa: E402


def _impression(text: str, sources: tuple[str, ...] = (),
                derived_from: tuple[str, ...] = ()) -> object:
    return make(
        "memory",
        {"text": text, "level": "impression"},
        strength=Strength(weight=1.5),
        scope="private",
        subject_id="u1",
        lineage=Lineage(sources=sources, derived_from=derived_from),
    )


class ImpressionLineageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db = open_store(os.path.join(tempfile.mkdtemp(prefix="seekmem_lineage_"), "t.db"))
        self.addCleanup(self.db.close)
        self.cache = Cache(self.db.artifacts)

    def test_reword_unions_sources_without_self_reference(self) -> None:
        old = _impression("he is stubborn", ("s1",))
        self.db.artifacts.commit(old, expected_revision=0, op="create")
        self.cache.put(old)
        incoming = _impression(
            "he is stubborn but helps when it really matters", ("s2",)
        )
        got = revise_impression(self.db.artifacts, self.cache, incoming)
        self.assertIsNotNone(got)
        self.assertEqual(content_of(got), "he is stubborn but helps when it really matters")
        self.assertEqual(got.header.lineage.sources, ("s1", "s2"))
        self.assertIn(incoming.header.id, got.header.lineage.derived_from)
        self.assertNotIn(got.header.id, got.header.lineage.derived_from)

    def test_reinforce_unions_sources(self) -> None:
        old = _impression("he is stubborn but helps", ("s1",))
        self.db.artifacts.commit(old, expected_revision=0, op="create")
        self.cache.put(old)
        incoming = _impression("he is stubborn but helps", ("s2",))
        got = revise_impression(self.db.artifacts, self.cache, incoming)
        self.assertIsNotNone(got)
        self.assertEqual(got.header.lineage.sources, ("s1", "s2"))

    def test_retire_keeps_cache_when_commit_fails(self) -> None:
        art = _impression("retire me", ("s1",))
        self.db.artifacts.commit(art, expected_revision=0, op="create")
        self.cache.put(art)
        with patch.object(self.db.artifacts, "commit", side_effect=RuntimeError("db down")):
            _retire(self.db, self.cache, art)
        self.assertIs(self.cache.get(art.header.id), art)


if __name__ == "__main__":
    unittest.main()
