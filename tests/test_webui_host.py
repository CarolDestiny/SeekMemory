"""针对 AstrBot 真实请求与插件 API 的可选集成测试。"""

from __future__ import annotations

import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT.parents[2]
if (HOST / "astrbot/api/web.py").is_file():
    sys.path.insert(0, str(HOST))
sys.path.insert(0, str(ROOT.parent))

try:
    from starlette.requests import Request

    from astrbot.api.web import PluginRequest, bind_request_context

except ImportError:
    Main = None
else:
    Main = importlib.import_module(f"{ROOT.name}.main").Main


class HostContext:
    def __init__(self) -> None:
        self.registered_web_apis = []
        self.provider = None

    def register_web_api(self, route, handler, methods, description) -> None:
        self.registered_web_apis.append((route, handler, methods, description))

    async def get_using_provider_async(self):
        return self.provider


@unittest.skipIf(Main is None, "AstrBot host is not installed")
class HostTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.context = HostContext()
        self.plugin = Main(
            self.context,
            {
                "db_path": str(Path(self.temp.name) / "memory.db"),
                "max_sessions_per_flush": 1,
            },
        )

    async def asyncTearDown(self) -> None:
        await self.plugin.terminate()
        self.temp.cleanup()

    async def request(
        self,
        action: str,
        method: str = "GET",
        body: dict | None = None,
        username: str | None = "admin",
    ):
        """绑定真实宿主请求，不启动消息适配器。

        Args:
            action: 管理接口操作。
            method: HTTP 方法。
            body: 可选 JSON 请求体。
            username: 宿主认证身份；认证失败测试使用 None。

        Returns:
            插件处理器返回的真实 JSON 响应。
        """

        async def receive():
            return {
                "type": "http.request",
                "body": json.dumps(body).encode(),
                "more_body": False,
            }

        raw = Request(
            {
                "type": "http",
                "method": method,
                "path": "/manage/" + action,
                "query_string": b"",
                "headers": [(b"content-type", b"application/json")],
            },
            receive,
        )
        with bind_request_context(PluginRequest(raw, username=username)):
            return await self.plugin.web.handle(action)

    async def test_auth_methods_and_confirmation(self) -> None:
        self.assertEqual(
            (await self.request("records", username=None)).status_code, 401
        )
        self.assertEqual((await self.request("update")).status_code, 405)
        self.assertEqual(
            (await self.request("task", "POST", {"kind": "weekly"})).status_code, 400
        )
        status = await self.request("status")
        self.assertEqual(status.status_code, 200)
        self.assertTrue(json.loads(status.body)["ready"])
        malformed = await self.request("task", "POST", {"kind": [], "confirmed": True})
        self.assertEqual(malformed.status_code, 400)

    async def test_provider_lookup_failure_preserves_other_checks(self) -> None:
        async def failing_provider():
            raise ValueError("private provider detail")

        self.context.get_using_provider_async = failing_provider
        response = await self.request("status")
        self.assertEqual(response.status_code, 200)
        result = json.loads(response.body)
        self.assertTrue(result["ready"])
        self.assertFalse(
            next(check for check in result["checks"] if check["name"] == "provider")[
                "ok"
            ]
        )
        self.assertNotIn("private provider detail", response.body.decode())

    async def test_host_discovers_built_page_and_exposes_expected_bridge(self) -> None:
        from astrbot.dashboard.services.plugin_page_service import PluginPageService

        entry = ROOT / "pages/memory/index.html"
        if not entry.exists():
            self.skipTest("Build the dashboard before testing host page discovery")
        service = PluginPageService(SimpleNamespace(plugin_store_path=ROOT.parent))
        metadata = SimpleNamespace(root_dir_name=ROOT.name, reserved=False)
        pages = await service.discover_plugin_pages(metadata)
        self.assertIn("memory", [page.name for page in pages])
        sdk = service.bridge_file.read_text(encoding="utf-8")
        self.assertIn("window.AstrBotPluginPage =", sdk)
        client = (ROOT / "dashboard/src/infrastructure/astrbot-client.ts").read_text(
            encoding="utf-8"
        )
        self.assertIn("window.AstrBotPluginPage", client)

    async def test_initialization_is_idempotent_and_shutdown_owns_resources(
        self,
    ) -> None:
        await self.plugin.initialize()
        await self.plugin.start_jobs()
        self.assertEqual(len(self.plugin._schedulers), 3)
        tasks = list(self.plugin._schedulers)
        await self.plugin.terminate()
        self.assertTrue(all(task.done() for task in tasks))
        self.assertEqual(self.context.registered_web_apis, [])
        self.assertIsNone(self.plugin.db)

    async def test_failed_extraction_preserves_buffer(self) -> None:
        class Provider:
            async def text_chat(self, **_kwargs):
                raise ValueError("private provider detail")

        self.context.provider = Provider()
        self.plugin.buffer.add("bot:FriendMessage:alice", "Remember this plan", "alice")
        with self.assertRaises(ValueError):
            await self.plugin._nightly()
        self.assertEqual(len(self.plugin.buffer.items), 1)
        persisted = json.loads((Path(self.temp.name) / "pending.json").read_text())
        self.assertEqual(len(persisted["items"]), 1)

    async def test_session_cap_and_new_messages_survive_success(self) -> None:
        plugin = self.plugin

        class Provider:
            async def text_chat(self, **_kwargs):
                plugin.buffer.add(
                    "bot:FriendMessage:alice", "Arrived during model call", "alice"
                )
                return SimpleNamespace(completion_text="[]")

        self.context.provider = Provider()
        plugin.buffer.add("bot:FriendMessage:alice", "Plan A", "alice")
        plugin.buffer.add("bot:FriendMessage:bob", "Plan B", "bob")
        await plugin._nightly()
        self.assertEqual(
            [row[3] for row in plugin.buffer.items],
            ["Plan B", "Arrived during model call"],
        )


if __name__ == "__main__":
    unittest.main()
