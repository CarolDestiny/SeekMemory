"""Self-impression and self-only persona regressions."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.artifact import Lineage, Strength, content_of, make  # noqa: E402
from maintain.persona import distill_self_persona  # noqa: E402
from maintain.self_impression import (  # noqa: E402
    SELF_SUBJECT,
    build_self_impressions,
    promote_self_candidates,
)
from perceive.extract import build_prompt  # noqa: E402
from store.cache import Cache  # noqa: E402
from store.db import DB  # noqa: E402


def _episode(action: str, source: str, subject: str = "u1"):
    return make(
        "memory",
        {"text": "episode text", "level": "scene", "bot_action": action,
         "bot_tone": "gentle", "bot_boundary": "do not decide for the user",
         "outcome": "accepted"},
        strength=Strength(weight=1.0),
        scope="private",
        subject_id=subject,
        lineage=Lineage(sources=(source,)),
    )


class SelfImpressionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db = DB(os.path.join(tempfile.mkdtemp(prefix="seekmem_self_"), "t.db"))
        self.addCleanup(self.db.close)
        self.cache = Cache(self.db)

    def seed(self, art) -> None:
        self.db.commit(art, expected_revision=0, op="create")
        self.cache.put(art)

    def test_prompt_requests_bot_behavior_fields(self) -> None:
        prompt = build_prompt([])
        for key in ("bot_action", "bot_tone", "bot_boundary", "outcome"):
            self.assertIn(key, prompt)

    def test_repeated_behavior_becomes_self_impression(self) -> None:
        for index in range(3):
            self.seed(_episode("validates emotion before asking facts", f"s{index}"))
        made = build_self_impressions(self.db, self.cache, min_hits=3)
        self.assertEqual(made, 1)
        candidates = promote_self_candidates(self.cache)
        self.assertEqual(len(candidates), 1)
        art = candidates[0]
        self.assertEqual(art.header.subject_id, SELF_SUBJECT)
        self.assertEqual(art.payload["level"], "impression")
        self.assertEqual(art.payload["about"], "self")
        self.assertEqual(art.header.scope, "shared")
        self.assertIn("validates emotion", content_of(art))
        self.assertEqual(set(art.header.lineage.sources), {"s0", "s1", "s2"})

    def test_user_impression_never_becomes_persona(self) -> None:
        user_imp = make(
            "memory", {"text": "he is stubborn", "level": "impression"},
            scope="private", subject_id="u1", strength=Strength(weight=2.0, hits=5),
        )
        self.seed(user_imp)
        self.assertIsNone(distill_self_persona(self.db, self.cache))

    def test_persona_id_is_stable_across_self_revisions(self) -> None:
        for index in range(3):
            self.seed(_episode("validates emotion before asking facts", f"s{index}"))
        first_made = build_self_impressions(self.db, self.cache, min_hits=3)
        first = distill_self_persona(self.db, self.cache)
        self.assertEqual(first_made, 1)
        self.assertIsNotNone(first)

        for index in range(3, 6):
            self.seed(_episode("admits uncertainty instead of inventing", f"s{index}"))
        second_made = build_self_impressions(self.db, self.cache, min_hits=3)
        second = distill_self_persona(self.db, self.cache)
        self.assertEqual(second_made, 1)
        self.assertIsNotNone(second)
        self.assertEqual(second.header.id, first.header.id)
        self.assertEqual(second.header.revision, 2)


if __name__ == "__main__":
    unittest.main()
