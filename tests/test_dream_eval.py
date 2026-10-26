"""Regression tests for the Dream tradeoff evaluation harness.

The harness is benchmark code, not production code. These tests protect two
things: the frozen corpus/measurement stays deterministic, and the harness
cannot quietly become a second Artifact write path or leak corpus text into a
report.
"""

from __future__ import annotations

import ast
import json
import sys
import traceback
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from benchmarks.dream_eval import (  # noqa: E402
    DEFAULT_CORPUS,
    THRESHOLDS,
    load_corpus,
    run_eval,
)
from store.artifacts import ArtifactRepository  # noqa: E402

HARNESS = ROOT / "benchmarks" / "dream_eval.py"
COMPARISON = ROOT / "benchmarks" / "dream_tradeoff.py"


class CorpusTest(unittest.TestCase):
    def test_frozen_corpus_covers_all_required_classes(self) -> None:
        rows = load_corpus(DEFAULT_CORPUS)
        self.assertGreaterEqual(len(rows), 30)
        self.assertTrue(all(row.get("synthetic") for row in rows))
        classes = {row["class"] for row in rows}
        self.assertEqual(classes, {"fact", "behavior", "chatter", "backlog"})
        self.assertGreater(
            sum(1 for row in rows if row["class"] == "fact"), 0
        )
        self.assertGreater(
            sum(1 for row in rows if row["class"] == "behavior"), 0
        )
        ids = [row["id"] for row in rows]
        self.assertEqual(len(ids), len(set(ids)))

    def test_corpus_text_is_never_present_in_the_report(self) -> None:
        rows = load_corpus(DEFAULT_CORPUS)
        payload = json.dumps(HarnessTest.report(), ensure_ascii=False)
        texts: list[str] = []
        for row in rows:
            texts.extend(str(turn["text"]) for turn in row["turns"])
            texts.extend(str(item["text"]) for item in row["recorded"])
        leaked = [text for text in texts if text and text in payload]
        self.assertEqual(leaked, [])


class HarnessTest(unittest.TestCase):
    @classmethod
    def report(cls) -> dict:
        cached = getattr(cls, "_report", None)
        if cached is None:
            cached = run_eval(ROOT, label="test", backlog_days=2)
            cls._report = cached
        return cached

    def test_runs_the_production_dream_and_ingest_path(self) -> None:
        report = self.report()
        paths = report["feature_paths"]
        self.assertTrue(paths["dream_cycle"])
        self.assertTrue(paths["ingest_service_flush"])
        self.assertTrue(paths["triage_parameter"])
        self.assertTrue(paths["usage_snapshot"])
        self.assertGreater(report["cost"]["extraction_calls"], 0)
        self.assertGreater(report["artifacts"]["extraction_written"], 0)
        self.assertEqual(report["dream"]["status"], "done")

    def test_topic_and_artifact_accounting_is_consistent(self) -> None:
        report = self.report()
        topics = report["topics"]
        pending = report["pending"]
        artifacts = report["artifacts"]
        self.assertEqual(
            topics["selected"] + topics["pending_topics"], topics["seen"]
        )
        self.assertEqual(
            pending["important_topics"] + pending["low_value_topics"],
            pending["topics"],
        )
        self.assertEqual(
            artifacts["extraction_written"]
            + artifacts["unclassified"]
            + artifacts["self_impressions"],
            artifacts["active_memory"],
        )
        self.assertEqual(report["dream"]["written"], artifacts["extraction_written"])

    def test_backlog_growth_is_reported_with_an_explicit_risk(self) -> None:
        backlog = self.report()["backlog"]
        self.assertGreaterEqual(len(backlog["per_day"]), 1)
        self.assertIn(backlog["risk"], {"none", "linear_unbounded"})
        if not backlog["bounded"]:
            self.assertEqual(backlog["risk"], "linear_unbounded")
            self.assertGreater(backlog["pending_delta"], 0)

    def test_measurement_is_deterministic(self) -> None:
        first = run_eval(ROOT, label="determinism", backlog_days=2)
        second = run_eval(ROOT, label="determinism", backlog_days=2)
        for key in (
            "cost",
            "topics",
            "triage",
            "artifacts",
            "quality",
            "pending",
            "dream",
            "backlog",
            "verdict",
            "feature_paths",
        ):
            self.assertEqual(first[key], second[key], key)

    def test_thresholds_are_explicit(self) -> None:
        report = self.report()
        self.assertEqual(report["verdict"]["thresholds"], THRESHOLDS)
        for key in (
            "important_fact_recall",
            "behavior_coverage",
            "self_impression_coverage",
            "false_memory_rate",
            "duplicate_rate",
            "pending_ratio",
        ):
            self.assertIn(key, report["verdict"]["checks"])

    def test_only_ingest_service_commits_extraction_artifacts(self) -> None:
        original = ArtifactRepository.commit
        callers: list[str] = []
        commits: list[str] = []

        def spy(instance, art, **kwargs):
            frames = traceback.extract_stack()
            callers.append(Path(frames[-2].filename).name)
            commits.append(art.header.id)
            return original(instance, art, **kwargs)

        with patch.object(ArtifactRepository, "commit", spy):
            report = run_eval(
                ROOT, label="write-path", maintenance=False, backlog_days=1
            )

        self.assertGreater(report["artifacts"]["extraction_written"], 0)
        self.assertEqual(len(commits), report["artifacts"]["extraction_written"])
        self.assertEqual(set(callers), {"ingest_service.py"})


class SourceGuardTest(unittest.TestCase):
    def _tree(self, path: Path) -> ast.Module:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    def test_harness_has_no_direct_write_or_network_primitive(self) -> None:
        tree = self._tree(HARNESS)
        forbidden_calls = {
            "commit",
            "commit_many",
            "upsert",
            "_persist_plan",
            "append_sources",
        }
        network_modules = {"urllib", "requests", "socket", "http", "httpx"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "attr", None) or getattr(
                    node.func, "id", None
                )
                self.assertNotIn(name, forbidden_calls)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn(alias.name.split(".")[0], network_modules)
            elif isinstance(node, ast.ImportFrom) and node.module:
                self.assertNotIn(node.module.split(".")[0], network_modules)
        source = HARNESS.read_text(encoding="utf-8")
        self.assertIn("services.ingest_service", source)
        self.assertIn("IngestService(", source)
        self.assertIn("DreamCycle(", source)

    def test_comparison_script_does_not_import_production_modules(self) -> None:
        tree = self._tree(COMPARISON)
        forbidden = {
            "app",
            "core",
            "perceive",
            "services",
            "store",
            "maintain",
            "recall",
        }
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.module:
                modules.append(node.module)
            elif isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            for module in modules:
                self.assertNotIn(module.split(".")[0], forbidden)


if __name__ == "__main__":
    unittest.main()
