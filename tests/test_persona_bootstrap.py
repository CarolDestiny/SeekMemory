"""Persona-file bootstrap and single persona chain."""
from __future__ import annotations

import unittest

from persona_support import PersonaCase
from core.artifact import Lineage, make
from core.bot_behavior import trusted_self_persona
from core.graph import Graph
from maintain.persona import distill_self_persona
from maintain.self_impression import build_self_impressions
from recall.pipeline import build_block
from services.management_service import ManagementService


def seed_file(text: str = "你是大肥鱼，说话温柔但有点嘴硬。") -> dict:
    return {
        "id": "big_fish",
        "version": "1.0.0",
        "name": "大肥鱼",
        "persona": text,
        "style": {"tone": "温柔嘴硬"},
        "boundaries": ["不伪造用户经历"],
        "corpus": [
            {"user": "今天好累。", "assistant": "先歇一下嘛，我陪你。"},
            {"user": "你会不会走？", "assistant": "才不走呢，别乱想。"},
        ],
        "license": "CC0-1.0",
        "source": "original",
        "content_rating": "general",
        "locale": "zh-CN",
    }


class PersonaBootstrapTest(PersonaCase):
    def service(self) -> ManagementService:
        return ManagementService(
            self.db.artifacts, self.db.sources, self.db.ledger, self.cache, None
        )

    def recall(self):
        return build_block(
            self.cache,
            Graph(self.db.artifacts),
            self.db.artifacts,
            self.db.sources,
            "owner",
            "你好",
            True,
            {"explore_rate": 0, "budget_chars": 600}.get,
            "owner",
            speaker="owner",
            dry_run=True,
        )

    def test_bootstrap_creates_one_trusted_seed_persona_without_source(self) -> None:
        result = self.service().bootstrap_persona(seed_file())
        active = self.cache.active("persona")
        self.assertEqual(len(active), 1)
        persona = active[0]
        self.assertEqual(result["id"], persona.header.id)
        self.assertEqual(persona.header.said_by, "seed")
        self.assertEqual(persona.header.lineage.sources, ())
        self.assertEqual(persona.payload["origin"], "seed")
        self.assertEqual(persona.payload["seed_id"], "big_fish")
        self.assertEqual(persona.payload["corpus_count"], 2)
        self.assertEqual(len(persona.payload["corpus"]), 2)
        self.assertEqual(len(persona.payload["corpus_hash"]), 64)
        self.assertTrue(trusted_self_persona(persona))

        block, info = self.recall()
        self.assertIn("大肥鱼", block)
        self.assertNotIn("先歇一下嘛", block)
        self.assertIn(persona.header.id, info["final_ids"])

    def test_bootstrap_revises_the_same_chain_and_retires_duplicates(self) -> None:
        first = self.seed(make("persona", {"text": "legacy one"}))
        self.seed(make("persona", {"text": "legacy two"}))
        service = self.service()
        result = service.bootstrap_persona(seed_file("第一版"))
        persona = self.cache.active("persona")[0]
        self.assertEqual(len(self.cache.active("persona")), 1)
        self.assertEqual(persona.header.revision, 2)
        self.assertEqual(len(self.db.artifacts.history(first.header.id)), 2)
        self.assertEqual(persona.payload["text"], "第一版")
        self.assertEqual(result["seedVersion"], "1.0.0")

        second = service.bootstrap_persona(seed_file("第二版"))
        persona = self.cache.active("persona")[0]
        self.assertEqual(second["id"], persona.header.id)
        self.assertEqual(persona.header.revision, 3)
        self.assertEqual(persona.payload["text"], "第二版")
        self.assertEqual(
            [row["payload"]["text"] for row in self.db.artifacts.history(persona.header.id)],
            ["legacy one", "第一版", "第二版"],
        )

    def test_dream_evolves_same_seed_lineage_and_keeps_evidence(self) -> None:
        self.service().bootstrap_persona(seed_file("你是大肥鱼，温柔但嘴硬。"))
        initial = self.cache.active("persona")[0]
        self.three()
        build_self_impressions(self.db.artifacts, self.db.sources, self.cache)
        evolved = distill_self_persona(self.db.artifacts, self.db.sources, self.cache)
        self.assertIsNotNone(evolved)
        assert evolved is not None
        self.assertEqual(evolved.header.id, initial.header.id)
        self.assertEqual(evolved.header.revision, 2)
        self.assertEqual(evolved.payload["origin"], "dream")
        self.assertEqual(evolved.payload["seed_id"], "big_fish")
        self.assertEqual(evolved.payload["corpus_count"], 2)
        self.assertEqual(evolved.payload["corpus"], initial.payload["corpus"])
        self.assertTrue(evolved.payload["text"].startswith("你是大肥鱼，温柔但嘴硬。"))
        self.assertIn(compose_behavior_text(evolved.payload["behaviors"]), evolved.payload["text"])
        self.assertTrue(evolved.header.lineage.sources)
        self.assertTrue(trusted_self_persona(evolved))

        block, info = self.recall()
        self.assertIn("大肥鱼", block)
        self.assertIn(evolved.header.id, info["final_ids"])

    def test_bootstrap_clears_legacy_lineage_and_creates_no_source(self) -> None:
        legacy = self.seed(make(
            "persona",
            {"text": "legacy"},
            lineage=Lineage(sources=("s1", "s2", "s3", "s4"), derived_from=("d1",)),
        ))
        before = self.db.sources.conn.execute("SELECT count(*) FROM sources").fetchone()[0]
        self.service().bootstrap_persona(seed_file())
        persona = self.cache.active("persona")[0]
        after = self.db.sources.conn.execute("SELECT count(*) FROM sources").fetchone()[0]
        self.assertEqual(persona.header.id, legacy.header.id)
        self.assertEqual(persona.header.lineage.sources, ())
        self.assertEqual(after, before)

    def test_bad_persona_file_does_not_write(self) -> None:
        bad = seed_file()
        bad.pop("persona")
        with self.assertRaises(ValueError):
            self.service().bootstrap_persona(bad)
        bad = seed_file()
        bad.pop("corpus")
        with self.assertRaises(ValueError):
            self.service().bootstrap_persona(bad)
        bad = seed_file()
        bad["command"] = "rm -rf"
        with self.assertRaises(ValueError):
            self.service().bootstrap_persona(bad)
        self.assertEqual(self.cache.active("persona"), [])


def compose_behavior_text(kinds: list[str]) -> str:
    from core.bot_behavior import compose_behaviors
    return compose_behaviors(kinds)


if __name__ == "__main__":
    unittest.main()
