"""管理修订、scope、只读预演与生命周期回归测试。"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.artifact import Lineage, make, revise  # noqa: E402
from core.graph import Graph  # noqa: E402
from core.source import Source  # noqa: E402
from store.cache import Cache  # noqa: E402
from store.db import DB  # noqa: E402
from store.ledger import Ledger  # noqa: E402
from webui.jobs import Jobs  # noqa: E402
from webui.journal import Journal  # noqa: E402
from webui.service import ManagementService  # noqa: E402


class ManagementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = DB(":memory:")
        self.addCleanup(self.db.close)
        self.cache = Cache(self.db.artifacts)
        self.service = ManagementService(
            self.db, self.cache, Graph(self.db, self.cache), {}.get
        )
        self.art = make(
            "memory",
            {
                "text": "Old fact",
                "level": "fact",
                "owner_umo": "bot:FriendMessage:alice",
            },
        )
        self.db.artifacts.upsert(self.art)
        self.cache.put(self.art)
        self.command = {
            "id": self.art.header.id,
            "expectedRevision": 1,
            "payload": {**self.art.payload, "text": "Corrected fact"},
            "scope": "private",
            "state": "active",
            "reason": "Correction",
            "confirmed": True,
        }

    def test_revision_is_atomic_and_old_content_survives(self) -> None:
        self.service.update(self.command)
        self.assertEqual(
            self.cache.get(self.art.header.id).payload["text"], "Corrected fact"
        )
        self.assertEqual(
            [item["payload"]["text"] for item in self.db.artifacts.history(self.art.header.id)],
            ["Old fact", "Corrected fact"],
        )
        self.assertTrue(Ledger(self.db.ledger).verify())
        with self.assertRaisesRegex(ValueError, "revision_conflict"):
            self.service.update(self.command)
        self.assertEqual(len(self.db.ledger.entries()), 1)

    def test_ledger_failure_rolls_back_revision_and_cache(self) -> None:
        with patch(
            "store.artifacts.append_ledger_conn", side_effect=RuntimeError("disk failure")
        ):
            with self.assertRaises(RuntimeError):
                self.service.update(self.command)
        self.assertEqual(self.db.artifacts.get(self.art.header.id), self.art)
        self.assertEqual(len(self.db.artifacts.history(self.art.header.id)), 1)
        self.assertEqual(self.cache.get(self.art.header.id), self.art)

    def test_kernel_revision_preserves_subject_and_version_evidence(self) -> None:
        source = Source("source-1", "turn-1", "session-1", "alice", "user", "原始事实")
        self.db.sources.append_sources([source])
        art = make(
            "memory",
            {"text": "原始事实", "level": "fact"},
            subject_id="alice",
            lineage=Lineage(sources=(source.id,)),
        )
        self.db.artifacts.commit(art, expected_revision=0, op="create", source_ids=(source.id,))
        self.cache.put(art)
        self.service.update({**self.command, "id": art.header.id})
        detail = self.service.detail(art.header.id)
        self.assertEqual(detail["artifact"]["header"]["subject_id"], "alice")
        self.assertEqual(
            [row["op"] for row in detail["versions"]], ["revise", "create"]
        )
        self.assertEqual([row["id"] for row in detail["sources"]], [source.id])
        self.assertEqual(detail["sources"][0]["text"], source.text)
        self.assertEqual(detail["ledger"][-1]["before_hash"], "1")
        self.assertEqual(detail["ledger"][-1]["after_hash"], "2")
        self.assertEqual(
            self.db.conn.execute(
                "SELECT revision FROM artifact_evidence WHERE entity=? ORDER BY revision",
                (art.header.id,),
            ).fetchall()[1][0],
            2,
        )
        record = next(
            row for row in self.service.catalog() if row["id"] == art.header.id
        )
        self.assertEqual(record["subject"], "alice")

    def test_forget_restore_and_invalid_payload(self) -> None:
        self.service.update({**self.command, "state": "forgotten"})
        self.assertIsNone(self.cache.get(self.art.header.id))
        self.service.update({**self.command, "expectedRevision": 2, "state": "active"})
        self.assertIsNotNone(self.cache.get(self.art.header.id))
        self.assertEqual(
            [row["op"] for row in self.db.ledger.entries()], ["forget", "revise"]
        )
        with self.assertRaises(ValueError):
            self.service.update(
                {**self.command, "expectedRevision": 3, "payload": {"text": "invalid"}}
            )
        self.assertEqual(self.db.artifacts.get(self.art.header.id).header.revision, 3)

    def test_merged_record_cannot_be_resurrected(self) -> None:
        with self.assertRaisesRegex(ValueError, "维护任务"):
            self.service.update({**self.command, "state": "merged"})
        self.db.artifacts.upsert(revise(self.art, state="merged"))
        with self.assertRaisesRegex(ValueError, "已合并"):
            self.service.update({**self.command, "expectedRevision": 2})

    def test_catalog_covers_every_family_and_scope(self) -> None:
        payloads = {
            "example": {"user": "hello", "assistant": "hi"},
            "persona": {"text": "patient"},
            "media": {"type": "web", "title": "Article", "url": "https://example.com"},
            "secret": {"ref": "private-reference", "shadow_text": "A promise"},
            "designated": {"text": "A reminder", "trigger": "reminder"},
        }
        for family, payload in payloads.items():
            self.db.artifacts.upsert(
                make(
                    family, payload, scope="shadow" if family == "secret" else "shared"
                )
            )
        records = self.service.catalog()
        self.assertEqual(len(records), 6)
        self.assertEqual(
            {row["scope"] for row in records}, {"private", "shared", "shadow"}
        )
        self.assertEqual(
            next(row for row in records if row["category"] == "secret")["text"],
            "A promise",
        )

    def test_diagnostic_respects_scope_without_consuming_delivery(self) -> None:
        art = make(
            "designated",
            {
                "text": "return this plan",
                "trigger": "plan",
                "owner_umo": "bot:FriendMessage:alice",
            },
        )
        self.db.artifacts.upsert(art)
        self.cache.put(art)
        before = self.db.conn.total_changes
        result = self.service.diagnose(
            {"query": "plan", "umo": "bot:FriendMessage:alice", "speaker": "alice"}
        )
        self.assertIn("return this plan", result["block"])
        self.assertEqual(self.db.conn.total_changes, before)
        self.assertNotIn("given", self.db.artifacts.get(art.header.id).payload)
        other = self.service.diagnose(
            {"query": "plan", "umo": "bot:FriendMessage:bob", "speaker": "bob"}
        )
        self.assertIn(art.header.id, other["excluded"])
        self.assertNotIn("return this plan", other["block"])


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.journal = Journal(Path(self.temp.name) / "lifecycle.jsonl")
        self.jobs = Jobs(self.journal)

    async def test_overlapping_tasks_and_shutdown(self) -> None:
        started = asyncio.Event()

        async def operation() -> None:
            started.set()
            await asyncio.Event().wait()

        task_id = self.jobs.submit("extract", operation)
        await started.wait()
        with self.assertRaises(RuntimeError):
            self.jobs.submit("weekly", operation)
        await self.jobs.close()
        states = [
            row["status"] for row in self.journal.events if row["taskId"] == task_id
        ]
        self.assertEqual(states, ["queued", "running", "cancelled"])
        with self.assertRaises(RuntimeError):
            self.jobs.submit("extract", operation)

    async def test_cancellation_before_start_is_terminal(self) -> None:
        self.jobs.submit("extract", lambda: asyncio.sleep(10))
        await self.jobs.close()
        self.assertEqual(self.journal.events[-1]["status"], "cancelled")

    async def test_failure_records_type_not_secret_exception_message(self) -> None:
        async def operation() -> None:
            raise ValueError("PRIVATE MODEL RESPONSE")

        self.jobs.submit("extract", operation)
        await self.jobs.task
        self.assertEqual(self.journal.events[-1]["status"], "failed")
        self.assertNotIn(
            "PRIVATE MODEL RESPONSE", self.journal.path.read_text(encoding="utf-8")
        )

    async def test_restart_recovers_interrupted_tasks_and_tolerates_bad_lines(
        self,
    ) -> None:
        self.journal.record("extract", "running", "Task started", "abandoned")
        self.journal.record("extract", "info", "One session processed", "abandoned")
        with self.journal.path.open("a", encoding="utf-8") as stream:
            stream.write("{broken\n")
        restored = Journal(self.journal.path)
        self.assertEqual(restored.events[-1]["status"], "interrupted")
        self.assertEqual(restored.events[-1]["taskId"], "abandoned")
        for index in range(510):
            restored.record("test", "info", str(index))
        self.assertEqual(len(restored.events), 500)
        self.assertTrue(
            all(
                isinstance(row, dict)
                for row in map(
                    json.loads,
                    restored.path.read_text(encoding="utf-8")
                    .replace("{broken\n", "")
                    .splitlines(),
                )
            )
        )


if __name__ == "__main__":
    unittest.main()
