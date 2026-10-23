"""#15 明确禁止把用户特征改成人格；旧预期由真实自我证据契约替代。"""
import unittest
from unittest.mock import patch

from persona_support import PersonaCase
from core.artifact import Strength, TimeSpan, make
from core.bot_behavior import BEHAVIORS, compose_behaviors, trusted_self_persona
from core.graph import Graph
from maintain.persona import compose, distill_persona, distill_self_persona
from maintain.promote import promote_candidates
from maintain.self_impression import build_self_impressions, promote_self_candidates
from recall.pipeline import build_block
from store.ledger import Ledger


class PersonaTest(PersonaCase):
    def prepare(self, kind="respond_emotion"):
        self.three(kind)
        build_self_impressions(self.db, self.cache)

    def test_bootstrap_stable_id_and_evidence_revisions(self):
        self.prepare()
        first = distill_self_persona(self.db, self.cache)
        self.assertTrue(trusted_self_persona(first))
        self.assertEqual(first.payload["text"], compose_behaviors(["respond_emotion"]))
        self.assertEqual(distill_persona(self.db, self.cache), first)
        self.assertEqual(len(self.db.history(first.header.id)), 1)
        self.episode()
        build_self_impressions(self.db, self.cache)
        second = distill_self_persona(self.db, self.cache)
        self.assertEqual(second.header.id, first.header.id)
        self.assertEqual(second.header.revision, 2)
        self.assertEqual(second.payload["text"], first.payload["text"])
        self.assertEqual(len(second.header.lineage.sources), 8)
        self.assertEqual([r["revision"] for r in self.db.history(first.header.id)], [1, 2])
        self.assertTrue(Ledger(self.db).verify())

    def test_user_impressions_rejected_by_both_compatibility_paths(self):
        art = self.seed(make("memory", {"text": "他有点倔", "about": "other",
                                        "level": "impression"}, subject_id="u1",
                             strength=Strength(weight=5, hits=100)))
        self.assertEqual(promote_candidates(self.cache), [])
        self.assertIsNone(distill_persona(self.db, self.cache))
        self.assertEqual(compose([art]), "")
        self.assertEqual(self.db.get(art.header.id), art)

    def test_fixed_text_composer_has_three_trait_limit(self):
        for kind in BEHAVIORS:
            self.prepare(kind)
        candidates = promote_self_candidates(self.cache)
        self.assertEqual(len(promote_candidates(self.cache)), 6)
        persona = distill_self_persona(self.db, self.cache)
        self.assertEqual(len(persona.payload["behaviors"]), 3)
        self.assertEqual(persona.payload["text"], compose(candidates))

    def test_legacy_persona_reuses_id_and_preserves_history(self):
        legacy = self.seed(make("persona", {"text": "许澄住在栖云城"}, id="legacy",
                                time=TimeSpan(created="2025-01-01T00:00:00")))
        extra = self.seed(make("persona", {"text": "other legacy"}, id="extra"))
        self.prepare()
        result = distill_self_persona(self.db, self.cache)
        self.assertEqual(result.header.id, legacy.header.id)
        self.assertEqual(result.header.subject_id, "bot:self")
        self.assertEqual(self.db.get(extra.header.id).header.state, "merged")
        self.assertEqual(len(self.cache.active("persona")), 1)
        self.assertEqual(self.db.history(legacy.header.id)[0]["payload"]["text"], legacy.payload["text"])
        self.assertNotIn("许澄", result.payload["text"])

    def test_extra_personas_retired_atomically_even_if_text_unchanged(self):
        self.prepare()
        original = distill_self_persona(self.db, self.cache)
        extra = self.seed(make("persona", {"text": "legacy"}))
        result = distill_self_persona(self.db, self.cache)
        self.assertEqual(result, original)
        self.assertIsNone(self.cache.get(extra.header.id))
        self.assertEqual(len(self.cache.active("persona")), 1)

    def test_partial_consolidation_failure_rolls_back_everything(self):
        self.prepare()
        original = self.seed(make("persona", {"text": "old"}, id="p1"))
        extra = self.seed(make("persona", {"text": "extra"}, id="p2"))
        ledger = self.db.ledger_entries()
        commit = self.db._commit_conn
        def fail_second(art, **kwargs):
            if art.header.id == extra.header.id:
                raise RuntimeError("busy")
            return commit(art, **kwargs)
        with patch.object(self.db, "_commit_conn", side_effect=fail_second):
            with self.assertRaises(RuntimeError):
                distill_self_persona(self.db, self.cache)
        self.assertEqual(self.db.get(original.header.id), original)
        self.assertEqual(self.cache.get(original.header.id), original)
        self.assertEqual(self.db.get(extra.header.id), extra)
        self.assertEqual(self.db.ledger_entries(), ledger)

    def test_no_qualified_evidence_keeps_existing_history(self):
        old = self.seed(make("persona", {"text": "old"}))
        self.assertIsNone(distill_self_persona(self.db, self.cache))
        self.assertEqual(self.db.get(old.header.id), old)

    def test_safe_persona_is_in_final_context_and_legacy_is_silent(self):
        unsafe = self.seed(make("persona", {"text": "许澄的秘密橙色纸鹤"}, scope="shared"))
        def recall():
            return build_block(self.cache, Graph(self.db, self.cache), self.db,
                               "unrelated", "你好", True,
                               {"explore_rate": 0, "budget_chars": 600}.get,
                               "owner", speaker="stranger", dry_run=True)
        block, info = recall()
        self.assertNotIn(unsafe.payload["text"], block)
        self.assertNotIn(unsafe.header.id, info["final_ids"])
        self.prepare()
        persona = distill_self_persona(self.db, self.cache)
        block, info = recall()
        self.assertIn(persona.payload["text"], block)
        self.assertIn(persona.header.id, info["final_ids"])
        self.assertNotIn("许澄", block)


if __name__ == "__main__":
    unittest.main()
