"""Architecture guardrails for application ownership boundaries."""

from __future__ import annotations

import ast
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestration.access import AccessPolicy  # noqa: E402
from orchestration.background_tasks import BackgroundTasks  # noqa: E402


class AccessPolicyTest(unittest.TestCase):
    def test_owner_and_trusted_modes(self) -> None:
        policy = AccessPolicy(
            mode="owner_and_trusted",
            owner_umo="bot:owner",
            trusted_ids=frozenset({"trusted"}),
            observe_groups=True,
        )
        self.assertTrue(policy.may_remember("bot:owner", "owner"))
        self.assertTrue(policy.may_remember("bot:friend:trusted", "trusted"))
        self.assertFalse(policy.may_remember("bot:friend:other", "other"))
        self.assertTrue(policy.may_observe("bot:GroupMessage:g1", "other"))
        self.assertFalse(policy.may_recall("bot:FriendMessage:other", "other"))

    def test_group_detection_is_explicit(self) -> None:
        self.assertTrue(AccessPolicy.is_group("bot:GroupMessage:g1"))
        self.assertFalse(AccessPolicy.is_group("bot:FriendMessage:u1"))


class MainOwnershipTest(unittest.TestCase):
    def setUp(self) -> None:
        self.source = (ROOT / "main.py").read_text(encoding="utf-8")

    def test_main_contains_no_host_extra_protocol(self) -> None:
        self.assertNotIn("_seekmemory_", self.source)

    def test_main_does_not_write_memory_or_episode_state_directly(self) -> None:
        forbidden = (
            "self.recorder.",
            "db.append_sources(",
            "buffer.add(",
            "make_source_id(",
        )
        for fragment in forbidden:
            self.assertNotIn(fragment, self.source)

    def test_main_stays_a_composition_and_hook_shell(self) -> None:
        self.assertLessEqual(len(self.source.splitlines()), 800)

    def test_start_jobs_remains_the_astrbot_loaded_hook(self) -> None:
        tree = ast.parse(self.source)
        start_jobs = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "start_jobs"
        )
        decorators = [
            ast.unparse(decorator) for decorator in start_jobs.decorator_list
        ]
        self.assertIn("filter.on_astrbot_loaded()", decorators)


class BackgroundTasksLifecycleTest(unittest.TestCase):
    def test_start_and_stop_are_idempotent(self) -> None:
        class Journal:
            def __init__(self):
                self.rows = []

            def record(self, *args, **kwargs):
                self.rows.append((args, kwargs))

        class RuntimeWorker:
            async def run_forever(self):
                await asyncio.Event().wait()

        class Dummy:
            pass

        async def run():
            background = BackgroundTasks(
                jobs=Dummy(),
                checkpoint=None,
                buffer=None,
                capacity=Dummy(),
                ingest=Dummy(),
                maintenance=Dummy(),
                dream=None,
                runtime_worker=RuntimeWorker(),
                journal=Journal(),
                config=lambda key, default: default,
                logger=Dummy(),
            )
            self.assertTrue(background.start())
            self.assertFalse(background.start())
            tasks = list(background.tasks)
            await background.stop()
            self.assertTrue(all(task.done() for task in tasks))
            self.assertEqual(background.tasks, [])
            await background.stop()

        import asyncio

        asyncio.run(run())


class LayerDependencyTest(unittest.TestCase):
    def _imports(self, root: Path) -> list[str]:
        values: list[str] = []
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    values.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    values.append(node.module)
        return values

    def test_runtime_does_not_import_astrbot(self) -> None:
        imports = self._imports(ROOT / "app" / "runtime")
        self.assertFalse([item for item in imports if item.startswith("astrbot")])

    def test_store_does_not_import_host_or_adapters(self) -> None:
        imports = self._imports(ROOT / "store")
        self.assertFalse(
            [
                item for item in imports
                if item.startswith("astrbot") or item.startswith("adapters")
            ]
        )

    def test_orchestration_does_not_import_host_or_adapters(self) -> None:
        imports = self._imports(ROOT / "orchestration")
        self.assertFalse(
            [
                item for item in imports
                if item.startswith("astrbot") or item.startswith("adapters")
            ]
        )


if __name__ == "__main__":
    unittest.main()
