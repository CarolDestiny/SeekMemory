"""RunRecorder owns the single write-back path for runtime runs."""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.runtime import (  # noqa: E402
    DBEpisodeStore,
    EpisodeRecorder,
    RunRecorder,
    EpisodeRecord,
)
from store.db import DB  # noqa: E402
from store.cache import Cache  # noqa: E402
from app.checkpoint import CheckpointManager  # noqa: E402
from core.artifact import make, revise  # noqa: E402


class FakeDB:
    def __init__(self):
        self.sources = []

    def append_sources(self, sources):
        self.sources.extend(sources)
        return len(sources)


class FakeBuffer:
    def __init__(self):
        self.rows = []

    def add(self, umo, text, sender="", source_id="", at="", **kwargs):
        self.rows.append((umo, text, sender, source_id, at, kwargs))


class FakeCheckpoint:
    def __init__(self):
        self.records = []

    def record(self, art, at=""):
        self.records.append((art, at))
        return True


class FakeEpisodes:
    def __init__(self):
        self.rows = []

    def record(self, episode):
        self.rows.append(episode)


class FakeCache:
    def __init__(self, items):
        self.items = items

    def get(self, art_id):
        return self.items.get(art_id)


class RunRecorderTest(unittest.TestCase):
    def setUp(self):
        self.db = FakeDB()
        self.buffer = FakeBuffer()
        self.checkpoint = FakeCheckpoint()
        self.episodes = FakeEpisodes()
        memory = SimpleNamespace(header=SimpleNamespace(family="memory"))
        self.recorder = RunRecorder(
            db=self.db,
            buffer=self.buffer,
            checkpoint=self.checkpoint,
            episodes=self.episodes,
            cache=FakeCache({"n1": memory}),
            clock=lambda: "2026-01-01T00:00:00",
        )

    def test_reply_write_back_is_idempotent_by_run_id(self):
        first = self.recorder.record_reply(
            run_id="run-1",
            session_id="s1",
            text="reply",
            speaker_id="bot",
            turn_id="turn-1",
            reply_to="user-1",
            recall_ids=("n1",),
        )
        second = self.recorder.record_reply(
            run_id="run-1",
            session_id="s1",
            text="reply",
            speaker_id="bot",
            turn_id="turn-1",
            reply_to="user-1",
            recall_ids=("n1",),
        )
        self.assertEqual(first, second)
        self.assertEqual(len(self.db.sources), 1)
        self.assertEqual(len(self.buffer.rows), 1)
        self.assertEqual(len(self.checkpoint.records), 0)
        self.assertEqual(first.run_id, "run-1")

    def test_only_successful_delivery_reinforces_staged_recall_once(self):
        self.recorder.record_reply(
            run_id="staged", session_id="s1", text="reply", speaker_id="bot",
            recall_ids=("n1", "n1"),
        )
        self.assertEqual(self.checkpoint.records, [])
        for _ in range(2):
            self.assertTrue(self.recorder.record_delivery(
                run_id="staged", session_id="s1", decision="reply", reason="direct",
            ))
        self.assertEqual(len(self.checkpoint.records), 1)
        self.assertEqual(len(self.episodes.rows), 1)

    def test_failed_episode_remains_retryable_without_duplicate_reinforcement(self):
        self.recorder.record_reply(
            run_id="retry", session_id="s1", text="reply", speaker_id="bot",
            recall_ids=("n1",),
        )
        with patch.object(self.episodes, "record", return_value=False):
            with self.assertRaises(RuntimeError):
                self.recorder.record_delivery(
                    run_id="retry", session_id="s1", decision="reply", reason="direct",
                )
        self.assertTrue(self.recorder.record_delivery(
            run_id="retry", session_id="s1", decision="reply", reason="direct",
        ))
        self.assertEqual(len(self.checkpoint.records), 1)
        self.assertEqual(len(self.episodes.rows), 1)

    def test_database_episode_failure_is_reported_and_retries(self):
        db = DB(":memory:")
        self.addCleanup(db.close)
        sink = DBEpisodeStore(db)
        self.recorder.episodes = EpisodeRecorder(sink)
        with patch.object(db, "append_runtime_episode", side_effect=OSError("fixture")):
            with self.assertRaises(RuntimeError):
                self.recorder.record_delivery(
                    run_id="db-retry", session_id="s1", decision="reply", reason="direct",
                )
        self.assertEqual(sink.last_error, "OSError")
        self.recorder.record_delivery(
            run_id="db-retry", session_id="s1", decision="reply", reason="direct",
        )
        self.assertEqual(len(db.list_runtime_episodes("s1")), 1)
        self.assertEqual(sink.last_error, "")

    def test_recorder_keeps_only_bounded_recent_run_metadata(self):
        self.recorder.max_records = 2
        for index in range(6):
            run_id = f"bounded-{index}"
            self.recorder.record_reply(
                run_id=run_id, session_id="s1", text="reply", speaker_id="bot",
            )
            self.recorder.record_delivery(
                run_id=run_id, session_id="s1", decision="reply", reason="direct",
            )
        self.assertLessEqual(len(self.recorder._replies), 2)
        self.assertLessEqual(len(self.recorder._episodes), 2)

    def test_delivery_retry_does_not_repeat_successful_partial_reinforcement(self):
        second = SimpleNamespace(header=SimpleNamespace(family="memory"))
        self.recorder.cache.items["n2"] = second
        calls = []
        def fail_second(art, at=""):
            calls.append(art)
            if art is second:
                raise OSError("fixture")
            return True
        with patch.object(self.checkpoint, "record", side_effect=fail_second):
            with self.assertRaises(OSError):
                self.recorder.record_delivery(
                    run_id="partial", session_id="s1", decision="reply", reason="direct",
                    recall_ids=("n1", "n2"),
                )
        self.recorder.record_delivery(
            run_id="partial", session_id="s1", decision="reply", reason="direct",
            recall_ids=("n1", "n2"),
        )
        self.assertEqual(len(calls), 2)
        self.assertEqual([row[0] for row in self.checkpoint.records], [second])

    def test_real_delivery_effects_wait_for_success_and_retry_failed_commit(self):
        db = DB(":memory:")
        self.addCleanup(db.close)
        cache = Cache(db)
        memory = make("memory", {"text": "remembered fact", "level": "scene"})
        designated = make("designated", {"text": "book list", "trigger": "book"})
        for artifact in (memory, designated):
            db.commit(artifact, expected_revision=0, op="create")
            cache.put(artifact)
        checkpoint = CheckpointManager(db, cache, cooldown_seconds=0)
        recorder = RunRecorder(
            db=db, buffer=None, checkpoint=checkpoint,
            episodes=EpisodeRecorder(DBEpisodeStore(db)), cache=cache,
        )
        recorder.record_reply(
            run_id="confirmed", session_id="s1", text="reply", speaker_id="bot",
            recall_ids=(memory.header.id,), designated_ids=(designated.header.id,),
        )
        self.assertEqual(checkpoint.pending(), 0)
        self.assertFalse(db.get(designated.header.id).payload.get("given"))
        with patch.object(db, "commit", side_effect=OSError("fixture")):
            with self.assertRaises(OSError):
                recorder.record_delivery(
                    run_id="confirmed", session_id="s1", decision="reply", reason="direct",
                )
        self.assertFalse(db.get(designated.header.id).payload.get("given"))
        self.assertEqual(db.list_runtime_episodes("s1"), [])
        for _ in range(2):
            recorder.record_delivery(
                run_id="confirmed", session_id="s1", decision="reply", reason="direct",
            )
        self.assertTrue(db.get(designated.header.id).payload.get("given"))
        checkpoint.flush()
        self.assertEqual(db.get(memory.header.id).header.strength.hits, 1)
        self.assertEqual(len(db.list_runtime_episodes("s1")), 1)

    def test_eviction_preserves_stable_source_and_database_episode_identity(self):
        db = DB(":memory:")
        self.addCleanup(db.close)
        recorder = RunRecorder(
            db=db, buffer=None, checkpoint=self.checkpoint,
            episodes=EpisodeRecorder(DBEpisodeStore(db)), max_records=1,
            cache=self.recorder.cache,
        )
        replies = []
        for run_id in ("first", "evict", "first"):
            reply = recorder.record_reply(
                run_id=run_id, session_id="s1", text="reply", speaker_id="bot",
            )
            replies.append(reply)
            recorder.record_delivery(
                run_id=run_id, session_id="s1", decision="reply", reason="direct",
                recall_ids=("n1",),
            )
        self.assertEqual(replies[0].assistant_source_id, replies[-1].assistant_source_id)
        self.assertEqual(len(db.list_runtime_episodes("s1")), 2)
        self.assertEqual(len(db.sources_by_ids([
            reply.assistant_source_id for reply in replies
        ])), 2)
        restarted = RunRecorder(
            db=db, buffer=None, checkpoint=self.checkpoint,
            episodes=EpisodeRecorder(DBEpisodeStore(db)), cache=self.recorder.cache,
        )
        restarted.record_delivery(
            run_id="first", session_id="s1", decision="reply", reason="direct",
            recall_ids=("n1",),
        )
        self.assertEqual(len(self.checkpoint.records), 2)

    def test_staged_delivery_does_not_consume_a_changed_designated_revision(self):
        db = DB(":memory:")
        self.addCleanup(db.close)
        cache = Cache(db)
        original = make("designated", {"text": "old book list", "trigger": "book"})
        db.commit(original, expected_revision=0, op="create")
        cache.put(original)
        recorder = RunRecorder(
            db=db, buffer=None, checkpoint=None,
            episodes=EpisodeRecorder(DBEpisodeStore(db)), cache=cache,
        )
        recorder.record_reply(
            run_id="revised", session_id="s1", text="reply", speaker_id="bot",
            designated_ids=(original.header.id,),
            designated_revisions={original.header.id: original.header.revision},
        )
        changed = revise(original, payload={"text": "new book list", "trigger": "book"})
        db.commit(changed, expected_revision=original.header.revision, op="revise")
        cache.put(changed)
        self.assertTrue(recorder.record_delivery(
            run_id="revised", session_id="s1", decision="reply", reason="direct",
        ))
        self.assertFalse(db.get(original.header.id).payload.get("given"))
        self.assertEqual(len(db.list_runtime_episodes("s1")), 1)

    def test_delivery_episode_is_idempotent_and_correlated(self):
        self.recorder.record_delivery(
            run_id="run-1",
            session_id="s1",
            decision="reply",
            reason="direct_attention",
            response_chars=5,
            tool_calls=("memory_search",),
            user_source_id="u1",
            assistant_source_id="a1",
        )
        self.recorder.record_delivery(
            run_id="run-1",
            session_id="s1",
            decision="reply",
            reason="direct_attention",
            response_chars=5,
            user_source_id="u1",
            assistant_source_id="a1",
        )
        self.assertEqual(len(self.episodes.rows), 1)
        row = self.episodes.rows[0]
        self.assertEqual(row.run_id, "run-1")
        self.assertTrue(row.delivered)
        self.assertEqual(row.tool_calls, ("memory_search",))

    def test_deferred_success_writes_source_and_episode_once(self):
        first = self.recorder.record_deferred_reply(
            run_id="run-deferred",
            session_id="s1",
            text="deferred reply",
            speaker_id="bot",
            user_source_id="u1",
            at="2026-01-01T00:00:01",
        )
        second = self.recorder.record_deferred_reply(
            run_id="run-deferred",
            session_id="s1",
            text="deferred reply",
            speaker_id="bot",
            user_source_id="u1",
            at="2026-01-01T00:00:01",
        )
        self.assertEqual(first, second)
        self.assertEqual(len(self.db.sources), 1)
        self.assertEqual(len(self.buffer.rows), 1)
        self.assertEqual(len(self.episodes.rows), 1)
        self.assertEqual(self.episodes.rows[0].assistant_source_id,
                         first.assistant_source_id)
        self.assertEqual(self.episodes.rows[0].run_id, "run-deferred")

    def test_deferred_error_records_safe_episode_without_assistant_source(self):
        self.recorder.record_deferred_error(
            run_id="run-error",
            session_id="s1",
            user_source_id="u1",
            error=RuntimeError("secret message"),
        )
        self.assertEqual(self.db.sources, [])
        self.assertEqual(len(self.episodes.rows), 1)
        row = self.episodes.rows[0]
        self.assertFalse(row.delivered)
        self.assertEqual(row.error, "RuntimeError")
        self.assertEqual(row.assistant_source_id, "")
        self.assertEqual(row.run_id, "run-error")

    def test_old_runtime_episode_table_migrates_run_id(self):
        path = os.path.join(tempfile.mkdtemp(prefix="seekmem_old_"), "memory.db")
        conn = sqlite3.connect(path)
        conn.execute(
            "CREATE TABLE runtime_episodes ("
            "id TEXT PRIMARY KEY, at TEXT NOT NULL, session_id TEXT NOT NULL, "
            "decision TEXT NOT NULL DEFAULT '', reason TEXT NOT NULL DEFAULT '', "
            "action TEXT NOT NULL DEFAULT '', delivered INTEGER NOT NULL DEFAULT 0, "
            "response_chars INTEGER NOT NULL DEFAULT 0, "
            "tool_calls TEXT NOT NULL DEFAULT '[]', outcome TEXT NOT NULL DEFAULT '', "
            "error TEXT NOT NULL DEFAULT '', user_source_id TEXT NOT NULL DEFAULT '', "
            "assistant_source_id TEXT NOT NULL DEFAULT '')"
        )
        conn.commit()
        conn.close()
        db = DB(path)
        self.addCleanup(db.close)
        db.append_runtime_episode({
            "id": "ep-old", "at": "2026-01-01T00:00:00", "session_id": "s1",
            "run_id": "run-old",
        })
        self.assertEqual(db.list_runtime_episodes("s1")[0]["run_id"], "run-old")

    def test_database_rejects_duplicate_episode_run_ids(self):
        db = DB(os.path.join(tempfile.mkdtemp(prefix="seekmem_recorder_"), "memory.db"))
        self.addCleanup(db.close)
        sink = DBEpisodeStore(db)
        recorder = EpisodeRecorder(sink)
        episode = EpisodeRecord(
            session_id="s1", at="2026-01-01T00:00:00", decision="reply",
            reason="direct", action="reply", delivered=True, outcome="ok",
            run_id="run-1",
        )
        recorder.record(episode)
        recorder.record(episode)
        self.assertEqual(sink.last_error, "")
        rows = db.list_runtime_episodes("s1")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["run_id"], "run-1")


if __name__ == "__main__":
    unittest.main()
