from __future__ import annotations

import ast
import asyncio
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.checkpoint import CheckpointManager
from app.contracts import ChatRequest
from app.flush_policy import decide_flush
from core.artifact import make, revise
from core.retrieval import RetrievalCandidate
from core.disclosure import DisclosureLevel, RecallScene, decide, safe_text
from core.source import Source, make_source_id
from core.versioning import StateEvent, VersionError, assert_next_revision
from perceive.model import ProviderChatModel
from recall.score import select
from store.db import DB
from store.cache import Cache
from store.ledger import Ledger


def _memory(subject="u1", scope="private", text="I have a job interview"):
    return make("memory", {"text": text, "level": "fact", "tags": "job interview"},
                subject_id=subject, scope=scope)


class SourceTest(unittest.TestCase):
    def test_id_is_stable_and_validate(self):
        sid = make_source_id(session_id="s", speaker_id="u1", role="user", text="hi", at="t")
        self.assertEqual(sid, make_source_id(session_id="s", speaker_id="u1", role="user", text="hi", at="t"))
        src = Source(sid, "turn", "s", "u1", "user", "hi", "t")
        src.validate()
        self.assertEqual(len(src.content_hash), 64)


class VersionTest(unittest.TestCase):
    def test_next_revision(self):
        first = _memory()
        second = revise(first, payload={"text": "new", "level": "fact"})
        assert_next_revision(None, first)
        assert_next_revision(first, second)
        with self.assertRaises(VersionError):
            assert_next_revision(first, first)


class CommitTest(unittest.TestCase):
    def test_cas_history_and_ledger(self):
        db = DB(os.path.join(tempfile.mkdtemp(), "t.db"))
        first = _memory(subject="owner")
        db.artifacts.commit(first, expected_revision=0, op="create", reason="test",
                  source_ids=("source-1",))
        self.assertEqual(db.artifacts.get(first.header.id).header.subject_id, "owner")
        second = revise(first, payload={"text": "updated", "level": "fact"})
        db.artifacts.commit(second, expected_revision=1, op="revise", reason="update")
        rows = db.artifacts.history(first.header.id)
        self.assertEqual([r["revision"] for r in rows], [1, 2])
        self.assertEqual([r["op"] for r in rows], ["create", "revise"])
        self.assertEqual(len(db.ledger.entries()), 2)
        self.assertTrue(Ledger(db.ledger).verify())
        self.assertEqual(db.conn.execute("SELECT COUNT(*) FROM artifact_evidence").fetchone()[0], 1)
        with self.assertRaises(VersionError):
            db.artifacts.commit(revise(second, payload={"text": "stale", "level": "fact"}), expected_revision=1, op="revise")
        bad_event = StateEvent("bad", first.header.id, 2, "reinforce", {}, "t")
        with self.assertRaises(VersionError):
            db.artifacts.commit(second, expected_revision=99, op="reinforce", state_events=(bad_event,))
        self.assertEqual(db.conn.execute("SELECT COUNT(*) FROM state_events WHERE id = 'bad'").fetchone()[0], 0)
        event = StateEvent("e1", first.header.id, 2, "reinforce", {"hits": 1}, "t")
        reinforced = revise(second, payload={"text": "updated", "level": "fact"})
        db.artifacts.commit(
            reinforced,
            expected_revision=2,
            op="reinforce",
            state_events=(event,),
        )
        self.assertEqual(
            db.conn.execute("SELECT COUNT(*) FROM state_events").fetchone()[0], 1
        )


class DisclosureTest(unittest.TestCase):
    def test_same_session_private_is_full(self):
        art = _memory(subject="owner", scope="private", text="secret detail")
        scene = RecallScene("s1", "owner", "owner", ("owner",))
        got = decide(art, scene, 1.0, origin_sessions=("s1",))
        self.assertEqual(got.level, DisclosureLevel.FULL)
    def test_cross_session_same_subject_is_paraphrase(self):
        art = _memory(subject="owner", scope="private", text="secret detail")
        scene = RecallScene("s2", "owner", "owner", ("owner",))
        got = decide(art, scene, 1.0, origin_sessions=("s1",))
        self.assertEqual(got.level, DisclosureLevel.PARAPHRASE)
        self.assertNotIn("secret detail", safe_text(art, got.level))
    def test_absent_third_party_and_shadow_are_not_full(self):
        art = _memory(subject="other", scope="shadow", text="secret")
        scene = RecallScene("s2", "owner", "owner", ("owner",))
        got = decide(art, scene, 1.0, origin_sessions=("s1",))
        self.assertIn(got.level, (DisclosureLevel.HINT, DisclosureLevel.SILENCE))


class FakeProvider:
    async def text_chat(self, system_prompt="", prompt=""):
        class Usage:
            input = 10
            input_cached = 2
            output = 3
        class Resp:
            completion_text = "ok"
            id = "r1"
            usage = Usage()
        return Resp()

    def meta(self):
        class Meta:
            id = "p1"
            model = "m1"
        return Meta()


class RetrievalCandidateTest(unittest.TestCase):
    def test_lexical_signal_participates_in_selection(self):
        plain = _memory(text="ordinary")
        lexical = _memory(text="bm25")
        got = select([RetrievalCandidate(plain), RetrievalCandidate(lexical, lexical=1.0)],
                     "unrelated query", 0.0, k=1, explore=0.0, gate=False)
        self.assertEqual([a.header.id for a in got], [lexical.header.id])

    def test_shared_cross_session_never_returns_raw_text(self):
        art = _memory(subject="u1", scope="shared", text="top secret phrase")
        art = make("memory", {**art.payload, "tags": "project"}, subject_id="u1",
                   scope="shared")
        scene = RecallScene("s2", "u1", "u1", ("u1",))
        got = decide(art, scene, 1.0, origin_sessions=("s1",))
        self.assertEqual(got.level, DisclosureLevel.PARAPHRASE)
        self.assertNotIn("top secret phrase", safe_text(art, got.level))


class StoreBoundaryTest(unittest.TestCase):
    def test_source_batch_and_subject_index(self):
        db = DB(os.path.join(tempfile.mkdtemp(), "t.db"))
        src = Source("s1", "turn1", "umo1", "u1", "user", "hello", "t")
        self.assertEqual(db.sources.append_sources([src]), 1)
        self.assertEqual(db.sources.append_sources([src]), 0)
        self.assertEqual(db.sources.source_umo("s1"), "umo1")
        art = _memory(subject="u1")
        cache = Cache(db.artifacts)
        cache.put(art)
        self.assertEqual([a.header.id for a in cache.by_subject("u1")], [art.header.id])


class CheckpointTest(unittest.TestCase):
    def test_checkpoint_creates_revision_and_state_event(self):
        db = DB(os.path.join(tempfile.mkdtemp(), "t.db"))
        cache = Cache(db.artifacts)
        art = _memory()
        db.artifacts.commit(art, expected_revision=0, op="create")
        cache.put(art)
        mgr = CheckpointManager(db.artifacts, cache, cooldown_seconds=0)
        mgr.record(art)
        mgr.record(art)
        self.assertEqual(mgr.flush(), 1)
        got = cache.get(art.header.id)
        self.assertEqual(got.header.revision, 2)
        self.assertEqual(got.header.strength.hits, 2)
        self.assertEqual(db.conn.execute("SELECT COUNT(*) FROM state_events").fetchone()[0], 1)


class ModelBoundaryTest(unittest.TestCase):
    def test_provider_adapter_normalizes(self):
        model = ProviderChatModel(FakeProvider())
        got = asyncio.run(model.complete(ChatRequest("s1", "sys", "hi")))
        self.assertEqual(got.text, "ok")
        self.assertEqual(got.usage_in, 10)
        self.assertEqual(got.provider_id, "p1")


class FlushPolicyTest(unittest.TestCase):
    def test_backlog_overrides_worth_now(self):
        got = decide_flush(pending=30, idle_seconds=31, worth_now=False,
                           flushes_today=0, idle_flush_seconds=180,
                           min_pending=8, max_flushes_per_day=2,
                           backlog_flush_at=30)
        self.assertTrue(got.should)
        self.assertEqual(got.reason, "backlog")

    def test_backlog_waits_for_quiet_window(self):
        got = decide_flush(pending=30, idle_seconds=10, worth_now=False,
                           flushes_today=0, idle_flush_seconds=180,
                           min_pending=8, max_flushes_per_day=2,
                           backlog_flush_at=30)
        self.assertFalse(got.should)

    def test_expired_topic_overrides_daily_cap(self):
        got = decide_flush(pending=2, idle_seconds=10, worth_now=False,
                           flushes_today=2, idle_flush_seconds=180,
                           min_pending=8, max_flushes_per_day=2,
                           backlog_flush_at=30, topic_age_seconds=86400,
                           topic_ttl_seconds=86400)
        self.assertTrue(got.should)
        self.assertEqual(got.reason, "topic_expired")

    def test_daily_cap_blocks(self):
        got = decide_flush(pending=100, idle_seconds=999, worth_now=True,
                           flushes_today=2, idle_flush_seconds=180,
                           min_pending=8, max_flushes_per_day=2,
                           backlog_flush_at=30)
        self.assertFalse(got.should)
        self.assertEqual(got.reason, "daily_cap")


class MigrationTest(unittest.TestCase):
    def test_old_nodes_table_gets_subject_id(self):
        path = os.path.join(tempfile.mkdtemp(), "old.db")
        con = sqlite3.connect(path)
        con.execute("CREATE TABLE nodes (id TEXT PRIMARY KEY, family TEXT, level TEXT, parent TEXT, blob TEXT, state TEXT, scope TEXT, strength TEXT, time TEXT, said_by TEXT, shareable TEXT, created_at TEXT, updated_at TEXT, revision INTEGER, lineage TEXT)")
        con.commit()
        con.close()
        db = DB(path)
        cols = {r[1] for r in db.conn.execute("PRAGMA table_info(nodes)")}
        self.assertIn("subject_id", cols)


class ImportBoundaryTest(unittest.TestCase):
    def _imports(self, path):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        out = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                out.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                out.append(node.module)
        return out
    def test_core_and_app_do_not_import_adapters(self):
        root = Path(__file__).resolve().parents[1]
        forbidden = ("astrbot", "store", "recall", "perceive", "maintain", "main")
        for folder in (root / "core", root / "app"):
            for path in folder.glob("*.py"):
                for name in self._imports(path):
                    self.assertFalse(name.split(".")[0] in forbidden, f"{path}: {name}")


if __name__ == "__main__":
    unittest.main()
