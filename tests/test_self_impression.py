"""#15 用独立助手证据替换旧的自由文本重复计数。"""
from dataclasses import replace
from unittest.mock import patch
import unittest

from persona_support import PersonaCase
from core.artifact import Lineage, Strength, make, revise
from core.bot_behavior import BEHAVIOR_TEXT, SELF_SUBJECT
from maintain.self_impression import build_self_impressions, promote_self_candidates
from maintain.promote import promote_candidates


class SelfImpressionTest(PersonaCase):
    def test_three_real_pairs_produce_safe_self_impression(self):
        episodes = self.three()
        self.assertEqual(build_self_impressions(self.db, self.cache), 1)
        art, = promote_self_candidates(self.cache, self.db.sources)
        self.assertEqual(art.header.subject_id, SELF_SUBJECT)
        self.assertEqual(art.header.scope, "shared")
        self.assertEqual(art.payload["about"], "self")
        self.assertEqual(art.payload["text"], BEHAVIOR_TEXT["respond_emotion"])
        self.assertEqual(art.header.strength.hits, 3)
        self.assertEqual(set(art.header.lineage.derived_from), {a.header.id for a in episodes})
        self.assertEqual(len(art.header.lineage.sources), 6)
        self.assertNotIn("许澄", str(art.payload))

    def test_same_assistant_in_three_artifacts_counts_once(self):
        first = self.episode()
        for i in range(2):
            self.seed(make("memory", {**first.payload, "text": str(i)},
                           lineage=first.header.lineage, strength=first.header.strength))
        self.assertEqual(build_self_impressions(self.db, self.cache), 0)

    def test_independent_assistant_replies_may_share_one_user_parent(self):
        from core.source import Source
        first = self.episode()
        parent = self.db.sources.sources_by_ids(["u1"])["u1"]
        for index in range(2, 4):
            reply = Source(f"a{index}", parent.turn_id, parent.session_id, "bot", "assistant",
                           f"different actual reply {index}", parent.at, reply_to=parent.id)
            self.db.sources.append_sources([reply])
            self.seed(make("memory", {**first.payload, "text": f"scene {index}"},
                           lineage=Lineage(sources=(parent.id, reply.id)),
                           strength=first.header.strength))
        self.assertEqual(build_self_impressions(self.db, self.cache), 1)
        art, = promote_self_candidates(self.cache, self.db.sources)
        self.assertEqual(len(art.header.lineage.sources), 4)
        self.assertEqual(art.header.strength.hits, 3)
        self.assertEqual(build_self_impressions(self.db, self.cache), 0)
        self.assertEqual(promote_self_candidates(self.cache, self.db.sources)[0].header.id, art.header.id)

    def test_threshold_low_confidence_and_legacy_do_not_bootstrap(self):
        self.episode()
        self.episode()
        for value in (0.89, float("nan"), float("inf"), -1):
            self.episode(confidence=value)
        self.assertEqual(build_self_impressions(self.db, self.cache), 0)
        self.seed(make("memory", {"text": "legacy", "level": "scene",
                                 "bot_action": "先回应情绪"}))
        self.assertEqual(build_self_impressions(self.db, self.cache), 0)

    def test_derived_artifact_and_broad_evidence_cannot_inflate_count(self):
        episodes = self.three()
        for a in episodes:
            self.cache.remove(a.header.id)
        self.seed(make("memory", {"text": "summary", "level": "scene",
                                 "bot_behavior": "respond_emotion"},
                       lineage=Lineage(sources=tuple(s for a in episodes for s in a.header.lineage.sources)),
                       strength=Strength(confidence=1)))
        self.assertEqual(build_self_impressions(self.db, self.cache), 0)
        self.seed(make("memory", episodes[0].payload,
                       lineage=Lineage(sources=episodes[0].header.lineage.sources,
                                       derived_from=(episodes[0].header.id,))))
        self.assertEqual(build_self_impressions(self.db, self.cache), 0)

    def test_no_recursive_count_and_new_evidence_revises_same_id(self):
        self.three()
        build_self_impressions(self.db, self.cache)
        first, = promote_self_candidates(self.cache, self.db.sources)
        self.assertEqual(build_self_impressions(self.db, self.cache), 0)
        self.episode()
        self.assertEqual(build_self_impressions(self.db, self.cache), 1)
        second, = promote_self_candidates(self.cache, self.db.sources)
        self.assertEqual(second.header.id, first.header.id)
        self.assertEqual(second.header.revision, 2)
        self.assertEqual(second.header.strength.hits, 4)
        self.assertNotIn(second.header.id, second.header.lineage.derived_from)

    def test_wrong_subject_about_and_user_impressions_are_not_promoted(self):
        self.three()
        build_self_impressions(self.db, self.cache)
        art, = promote_self_candidates(self.cache, self.db.sources)
        self.cache.remove(art.header.id)
        for kw in ({"subject_id": "user"}, {"payload": {**art.payload, "about": "other"}},
                   {"payload": {**art.payload, "text": "许澄住在栖云城"}}):
            invalid = revise(art, **kw)
            self.cache.put(invalid)
            self.assertEqual(promote_candidates(self.cache, self.db.sources), [])
            self.cache.remove(invalid.header.id)

    def test_evidence_must_really_exist_and_pair(self):
        episodes = self.three()
        with patch.object(self.db.sources, "sources_by_ids", return_value={}):
            self.assertEqual(build_self_impressions(self.db, self.cache), 0)
        broken = self.db.sources.sources_by_ids([s for a in episodes for s in a.header.lineage.sources])
        broken["a1"] = replace(broken["a1"], session_id="wrong")
        with patch.object(self.db.sources, "sources_by_ids", return_value=broken):
            self.assertEqual(build_self_impressions(self.db, self.cache), 0)

    def test_commit_failure_does_not_update_cache_or_ledger(self):
        self.three()
        before = self.db.ledger.entries()
        with patch("store.artifacts.append_ledger_conn", side_effect=RuntimeError("busy")):
            with self.assertRaises(RuntimeError):
                build_self_impressions(self.db, self.cache)
        self.assertEqual(promote_self_candidates(self.cache, self.db.sources), [])
        self.assertEqual(self.db.ledger.entries(), before)


if __name__ == "__main__":
    unittest.main()
