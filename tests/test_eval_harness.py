"""Evaluation and read-only probe harness tests."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from benchmarks.real_eval import load_cases, score_items  # noqa: E402
from core.artifact import make  # noqa: E402
from scripts.live_probe import probe  # noqa: E402
from scripts.snapshot_db import snapshot  # noqa: E402
from store.db import DB  # noqa: E402


class EvalHarnessTest(unittest.TestCase):
    def test_case_scoring_uses_expected_texts(self) -> None:
        score = score_items(
            [{"text": "The owner lives in Shanghai", "level": "fact"}],
            {"texts": ["Shanghai"]},
        )
        self.assertTrue(score["schema_ok"])
        self.assertEqual(score["expected_hits"], 1)

    def test_fixture_loads(self) -> None:
        cases = load_cases("benchmarks/data/extraction_smoke.jsonl")
        self.assertGreaterEqual(len(cases), 2)
        self.assertEqual(cases[0]["id"], "plan_change")


class SnapshotTest(unittest.TestCase):
    def test_snapshot_preserves_counts(self) -> None:
        directory = tempfile.mkdtemp(prefix="seekmem_snapshot_")
        source = os.path.join(directory, "source.db")
        target = os.path.join(directory, "target.db")
        db = DB(source)
        db.artifacts.commit(make("memory", {"text": "snapshot fact", "level": "fact"}),
                  expected_revision=0, op="create")
        db.close()
        snapshot(source, target)
        self.assertEqual(probe(source)["active_nodes"], probe(target)["active_nodes"])


class LiveProbeTest(unittest.TestCase):
    def test_probe_reads_counts_and_ledger(self) -> None:
        path = os.path.join(tempfile.mkdtemp(prefix="seekmem_probe_"), "t.db")
        db = DB(path)
        art = make("memory", {"text": "probe fact", "level": "fact"})
        db.artifacts.commit(art, expected_revision=0, op="create")
        db.close()
        result = probe(path, "test")
        self.assertEqual(result["label"], "test")
        self.assertEqual(result["active_nodes"], 1)
        self.assertTrue(result["ledger_ok"])


if __name__ == "__main__":
    unittest.main()
