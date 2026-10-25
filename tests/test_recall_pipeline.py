from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.budget import ContextBudget
from core.artifact import Lineage, make
from core.graph import Graph
from core.source import Source
from recall.pipeline import build_block
from recall.retriever import HybridRetriever
from services.recall_service import RecallService
from store.cache import Cache
from store import open_store
from services.management_service import ManagementService


class PipelineDisclosureTest(unittest.TestCase):
    def test_cross_session_shared_memory_is_paraphrased(self):
        db = open_store(os.path.join(tempfile.mkdtemp(), "t.db"))
        cache = Cache(db.artifacts)
        graph = Graph(db.artifacts)
        src = Source("s1", "turn1", "s1", "u1", "user", "source text", "t")
        db.sources.append_sources([src])
        art = make("memory", {"text": "top secret phrase", "level": "scene",
                              "tags": "project"}, subject_id="u1", scope="shared")
        db.artifacts.commit(art, expected_revision=0, op="create", source_ids=("s1",))
        cache.put(art)
        config = {"bm25_enabled": True}
        block, info = build_block(
            cache, graph, db.artifacts, db.sources, "s2", "top secret phrase", True,
            lambda key, default: config.get(key, default),
            "napcat:FriendMessage:u1", "u1",
            hybrid_retriever=HybridRetriever(graph, cache),
        )
        self.assertTrue(block)
        self.assertNotIn("top secret phrase", block)
        self.assertEqual(info["disclosure"][art.header.id], "paraphrase")

    def test_bm25_makes_private_memory_globally_retrievable_but_not_raw(self):
        db = open_store(os.path.join(tempfile.mkdtemp(), "t.db"))
        cache = Cache(db.artifacts)
        graph = Graph(db.artifacts)
        source = Source("s1", "turn1", "s1", "u1", "user", "private source", "t")
        db.sources.append_sources([source])
        art = make(
            "memory", {"text": "唯一的量化交易私密短语", "level": "scene"},
            scope="private", subject_id="u1",
        )
        db.artifacts.commit(art, expected_revision=0, op="create", source_ids=("s1",))
        cache.put(art)
        config = {"bm25_enabled": True}

        block, info = build_block(
            cache, graph, db.artifacts, db.sources, "s2", "还记得唯一的量化交易私密短语吗", True,
            lambda key, default: config.get(key, default),
            "napcat:FriendMessage:u1", "u2",
            hybrid_retriever=HybridRetriever(graph, cache),
        )

        self.assertNotIn("唯一的量化交易私密短语", block)
        self.assertEqual(info["picked_ids"], (art.header.id,))
        self.assertIn(info["disclosure"].get(art.header.id), ("hint", "paraphrase", "silence"))


class OptionalBM25PipelineTest(unittest.TestCase):
    def setUp(self):
        self.db = open_store(":memory:")
        self.addCleanup(self.db.close)
        self.cache = Cache(self.db.artifacts)
        self.graph = Graph(self.db.artifacts)
        self.session = "bot:FriendMessage:u1"
        self.conf = {"bm25_enabled": True, "owner_umo": self.session,
                     "explore_rate": 0.0}
        self.retriever = HybridRetriever(self.graph, self.cache)

    def save(self, family, payload, scope="private"):
        number = self.cache.size()
        source = Source(f"s{number}", f"turn{number}", self.session, "u1", "user",
                        "synthetic fixture", "2026-10-22T12:00:00")
        self.db.sources.append_sources([source])
        art = make(family, {**payload, "owner_umo": self.session}, scope=scope,
                   subject_id="u1", lineage=Lineage(sources=(source.id,)))
        self.db.artifacts.commit(art, expected_revision=0, op="create", source_ids=(source.id,))
        self.cache.put(art)
        return art

    def recall(self, query, config=None, injected=None):
        return build_block(
            self.cache, self.graph, self.db.artifacts, self.db.sources, self.session, query, True,
            (config or self.conf).get, self.session, "u1", dry_run=True,
            hybrid_retriever=injected or self.retriever,
        )

    def save_tagged_case(self):
        from benchmarks.bm25_holdout import HOLDOUT_CASES

        case = next(case for case in HOLDOUT_CASES if case.id == "tagged_spare_item")
        for doc in case.distractors:
            self.save("memory", {"text": doc.text, "tags": list(doc.tags), "level": "fact"})
        target = self.save("memory", {"text": case.target.text,
                                     "tags": list(case.target.tags), "level": "fact"})
        # loose 模式会加 2，对齐离线独立验收的有效 top-8。
        self.conf["recall_k"] = 6
        return case.query, target

    def test_disabled_bm25_keeps_legacy_selection(self):
        query, target = self.save_tagged_case()
        disabled = {**self.conf, "bm25_enabled": False}
        block, info = self.recall(query, disabled)
        self.assertNotIn(target.header.id, info["picked_ids"])
        self.assertNotIn("第二格抽屉", block)

    def test_default_bm25_recovers_tagged_memory_through_real_pipeline(self):
        query, target = self.save_tagged_case()
        schema_path = Path(__file__).resolve().parents[1] / "_conf_schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        defaults = {**self.conf, "bm25_enabled": schema["bm25_enabled"]["default"]}
        absent = {key: value for key, value in self.conf.items() if key != "bm25_enabled"}
        for config in (defaults, absent):
            with self.subTest(config=config):
                block, info = self.recall(query, config)
                self.assertIn(target.header.id, info["picked_ids"])
                self.assertIn("第二格抽屉", block)

    def test_disabled_bm25_ignores_invalid_lexical_weight(self):
        target = self.save("memory", {"text": "最近在复习量化交易", "level": "fact"})
        for weight in (float("nan"), float("inf"), "invalid", None):
            config = {**self.conf, "bm25_enabled": False, "bm25_weight": weight}
            with self.subTest(weight=weight):
                block, info = self.recall("还记得量化交易吗", config)
                self.assertIn(target.header.id, info["picked_ids"])
                self.assertIn("最近在复习量化交易", block)

    def test_shadow_and_secret_never_inject_bodies_with_bm25(self):
        self.save("memory", {"text": "影子中不能公开的量化密码", "level": "fact"}, "shadow")
        self.save("secret", {"ref": "secret-reference", "shadow_text": "量化私密承诺"})
        block, info = self.recall("还记得量化密码和私密承诺吗")
        self.assertNotIn("影子中不能公开的量化密码", block)
        self.assertNotIn("secret-reference", block)
        self.assertNotIn("量化私密承诺", block)
        self.assertNotIn("full", info["disclosure"].values())

    def test_readonly_diagnosis_does_not_consume_designated_delivery(self):
        designated = self.save("designated", {"text": "归还书籍清单", "trigger": "书籍"})
        recall_service = RecallService(
            cache=self.cache,
            graph=self.graph,
            artifacts=self.db.artifacts,
            sources=self.db.sources,
            budget=SimpleNamespace(injection_chars=600),
            config=self.conf.get,
            owner_umo=lambda: self.conf["owner_umo"],
            hybrid_retriever=self.retriever,
        )
        service = ManagementService(
            artifacts=self.db.artifacts,
            sources=self.db.sources,
            ledger=self.db.ledger,
            cache=self.cache,
            recall_service=recall_service,
        )
        result = service.diagnose({"query": "还记得书籍吗", "umo": self.session,
                                   "speaker": "u1"})
        self.assertIn("归还书籍清单", result["block"])
        self.assertEqual(self.db.artifacts.get(designated.header.id), designated)

    def test_clock_question_does_not_retrieve_bm25_matches(self):
        self.save("memory", {"text": "今天几号的问题", "level": "fact"})
        block, info = self.recall("今天几号")
        self.assertEqual(info["picked_ids"], ())
        self.assertEqual(block, "")

    def test_enabled_bm25_recovers_tagged_memory_through_real_pipeline(self):
        query, target = self.save_tagged_case()
        block, new_info = self.recall(query)
        self.assertIn(target.header.id, new_info["picked_ids"])
        self.assertIn("第二格抽屉", block)


if __name__ == "__main__":
    unittest.main()




class CountingSources:
    def __init__(self, repo):
        self.repo = repo
        self.recent_calls = 0

    def recent_sources(self, *, since, limit):
        self.recent_calls += 1
        return self.repo.recent_sources(since=since, limit=limit)

    def __getattr__(self, name):
        return getattr(self.repo, name)


class SourceRecallPipelineTest(unittest.TestCase):
    def setUp(self):
        self.db = open_store(":memory:")
        self.addCleanup(self.db.close)
        self.cache = Cache(self.db.artifacts)
        self.graph = Graph(self.db.artifacts)
        self.session = "bot:FriendMessage:u1"
        self.sources = CountingSources(self.db.sources)
        self.conf = {
            "bm25_enabled": True,
            "recall_k": 8,
            "budget_chars": 600,
            "source_recall_enabled": True,
            "source_recall_hours": 12,
            "source_recall_max_candidates": 80,
        }
        self.by_source_calls = 0
        original = self.db.artifacts.by_source_ids
        def counted(source_ids):
            self.by_source_calls += 1
            return original(source_ids)
        self.db.artifacts.by_source_ids = counted

    def add_source(self, source_id, text, *, session=None, speaker="u1"):
        import datetime
        at = datetime.datetime.now().isoformat(timespec="seconds")
        self.db.sources.append_sources([
            Source(source_id, "turn-" + source_id, session or self.session,
                   speaker, "user", text, at)
        ])

    def add_artifact(self, text, *, source_ids=(), cache=True, scope="shared"):
        art = make(
            "memory", {"text": text, "level": "fact"},
            scope=scope, subject_id="u1",
            lineage=Lineage(sources=tuple(source_ids)),
        )
        self.db.artifacts.commit(
            art, expected_revision=0, op="create", source_ids=tuple(source_ids)
        )
        if cache:
            self.cache.put(art)
        return art

    def recall(self, query, **changes):
        conf = {**self.conf, **changes}
        return build_block(
            self.cache, self.graph, self.db.artifacts, self.sources,
            self.session, query, True, conf.get, self.session, "u1",
            dry_run=True,
        )

    def test_memory_sufficient_does_not_query_sources(self):
        self.add_artifact("quantum trading alpha")
        self.add_artifact("quantum trading beta")
        block, info = self.recall("quantum trading")
        self.assertTrue(block)
        self.assertEqual(self.sources.recent_calls, 0)
        self.assertEqual(self.by_source_calls, 0)
        self.assertEqual(info["source_recall"]["candidates"], 0)

    def test_weak_memory_uses_one_source_query_and_one_batch_lookup(self):
        self.add_artifact("quantum trading picked")
        self.add_source("s1", "quantum trading source note")
        self.add_artifact("derived quantum one", source_ids=("s1",), cache=False)
        self.add_artifact("derived quantum two", source_ids=("s1",), cache=False)
        block, info = self.recall("quantum trading")
        self.assertEqual(self.sources.recent_calls, 1)
        self.assertEqual(self.by_source_calls, 1)
        self.assertEqual(info["source_recall"]["candidates"], 1)
        self.assertEqual(info["source_recall"]["artifacts"], 2)
        self.assertEqual(info["source_recall"]["picked"], 2)
        self.assertIn("derived quantum one", block)
        self.assertNotIn("quantum trading source note", block)

    def test_pinned_persona_does_not_gate_source_evidence(self):
        persona = make(
            "persona", {"text": "stable persona", "traits": []},
            scope="shared", subject_id="u1",
        )
        self.db.artifacts.commit(persona, expected_revision=0, op="create")
        self.cache.put(persona)
        self.add_source("s1", "quantum trading source note")
        self.add_artifact("derived quantum", source_ids=("s1",), cache=False)
        block, info = self.recall("quantum trading")
        self.assertEqual(self.sources.recent_calls, 1)
        self.assertGreaterEqual(info["source_recall"]["picked"], 1)
        self.assertIn("derived quantum", block)

    def test_source_hit_rank_controls_artifact_when_capacity_is_one(self):
        self.add_artifact("quantum picked")
        self.add_source("sA", "quantum alpha top source")
        self.add_source("sB", "quantum beta source")
        self.add_artifact("artifact from B", source_ids=("sB",), cache=False)
        self.add_artifact("artifact from A", source_ids=("sA",), cache=False)
        block, info = self.recall(
            "quantum alpha top", recall_k=2
        )
        self.assertEqual(info["source_recall"]["picked"], 1)
        self.assertIn("artifact from A", block)
        self.assertNotIn("artifact from B", block)

    def test_cross_session_source_text_never_reaches_block(self):
        self.add_source("s1", "cross session quantum secret", session="other:session")
        self.add_artifact("cross evidence memory", source_ids=("s1",), cache=False)
        block, info = self.recall("quantum trading")
        self.assertEqual(self.sources.recent_calls, 1)
        self.assertEqual(info["source_recall"]["candidates"], 1)
        self.assertNotIn("cross session quantum secret", block)

    def test_source_recall_disabled_preserves_legacy_empty_info_shape(self):
        self.add_source("s1", "disabled quantum source")
        conf = {**self.conf, "source_recall_enabled": False}
        block, info = build_block(
            self.cache, self.graph, self.db.artifacts, self.sources,
            self.session, "quantum trading", True, conf.get, self.session, "u1",
            dry_run=True,
        )
        self.assertEqual(block, "")
        self.assertNotIn("source_recall", info)
        self.assertEqual(
            set(info),
            {"mode", "picked", "pinned", "chars", "picked_ids", "pinned_ids",
             "disclosure", "fallback", "candidates", "gate"},
        )


class SourceRecallBudgetTest(unittest.TestCase):
    def test_context_budget_disables_source_recall_without_config_key(self):
        db = open_store(":memory:")
        self.addCleanup(db.close)
        cache = Cache(db.artifacts)
        graph = Graph(db.artifacts)
        session = "bot:FriendMessage:u1"
        import datetime
        db.sources.append_sources([
            Source("s1", "turn-s1", session, "u1", "user",
                   "quantum trading source", datetime.datetime.now().isoformat(
                       timespec="seconds"))
        ])
        service = RecallService(
            cache=cache,
            graph=graph,
            artifacts=db.artifacts,
            sources=db.sources,
            budget=ContextBudget(
                injection_chars=600, source_recall_enabled=False
            ),
            config={}.get,
            owner_umo=lambda: session,
        )
        result = service.preview("quantum trading", session, True, "u1")
        self.assertEqual(result["block"], "")
        self.assertNotIn("source_recall", result["info"])
