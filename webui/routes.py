"""AstrBot bridge adapter for authenticated administrative requests."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from .service import ManagementService

if TYPE_CHECKING:
    from ..main import Main


class WebRoutes:
    """Own the routes registered by this plugin instance."""

    def __init__(self, plugin: Main) -> None:
        self.plugin = plugin

    def register(self) -> None:
        """Register host-native API handlers when the supported web API exists."""
        try:
            import astrbot.api.web  # noqa: F401
        except ImportError:
            self.plugin.journal.record(
                "webui", "warning", "Host plugin web API is unavailable"
            )
            return
        self.plugin.context.register_web_api(
            "/astrbot_plugin_seekmemory/manage/<action>",
            self.handle,
            ["GET", "POST"],
            "SeekMemory administration",
        )

    def close(self) -> None:
        """Remove only routes still owned by this instance, preserving replacements."""
        routes = self.plugin.context.registered_web_apis
        routes[:] = [route for route in routes if route[1] != self.handle]

    async def handle(self, action: str):
        """Dispatch authenticated administrative operations.

        Args:
            action: One of the explicitly supported administrative endpoints.

        Returns:
            A host-native JSON response with bounded diagnostics or an error.
        """
        from astrbot.api.web import error_response, json_response, request

        plugin = self.plugin
        if not request.username:
            return error_response("需要管理员登录", status_code=401)
        read_actions = {"status", "records", "detail", "events"}
        write_actions = {"update", "diagnose", "task", "cancel"}
        if action not in read_actions | write_actions:
            return error_response("未知操作", status_code=404)
        if request.method != ("GET" if action in read_actions else "POST"):
            return error_response("请求方法不支持", status_code=405)
        try:
            if action == "events":
                kind = request.query.get("kind", "")
                status = request.query.get("status", "")
                search = request.query.get("search", "").casefold()
                events = [
                    row
                    for row in reversed(plugin.journal.events)
                    if (not kind or row["kind"] == kind)
                    and (not status or row["status"] == status)
                    and (
                        not search
                        or search in (row["message"] + row["taskId"]).casefold()
                    )
                ]
                return json_response({"events": events, "capacity": 500})
            if action == "status":
                from ..store.ledger import Ledger

                checks = [
                    {"name": "engine", "ok": plugin.ready, "detail": "Memory engine"},
                    {
                        "name": "journal",
                        "ok": not plugin.journal.persistence_error,
                        "detail": "Lifecycle persistence",
                    },
                ]
                if plugin.db is not None:
                    checks.append(
                        {
                            "name": "ledger",
                            "ok": Ledger(plugin.db).verify(),
                            "detail": "Ledger hash chain",
                        }
                    )
                try:
                    provider = await plugin.context.get_using_provider_async()
                    provider_detail = "Configured provider; no model request sent"
                except Exception as exc:
                    provider = None
                    provider_detail = f"Provider lookup failed: {type(exc).__name__}"
                checks.append(
                    {
                        "name": "provider",
                        "ok": provider is not None,
                        "detail": provider_detail,
                    }
                )
                pending = (
                    Counter(row[0] for row in plugin.buffer.items)
                    if plugin.buffer is not None
                    else Counter()
                )
                active = plugin.jobs.task is not None and not plugin.jobs.task.done()
                return json_response(
                    {
                        "ready": plugin.ready,
                        "checks": checks,
                        "activeTask": {
                            "id": plugin.jobs.task_id,
                            "kind": plugin.jobs.kind,
                        }
                        if active
                        else None,
                        "pending": [
                            {"session": key, "count": value}
                            for key, value in pending.items()
                        ],
                        "schedulerCount": sum(
                            not task.done() for task in plugin._schedulers
                        ),
                        "config": {
                            key: plugin.cfg.get(key)
                            for key in (
                                "owner_umo",
                                "open_to",
                                "observe_groups",
                                "summary_time",
                                "weekly_day",
                                "idle_flush_seconds",
                                "max_sessions_per_flush",
                                "budget_chars",
                                "recall_k",
                                "trusted",
                                "explore_rate",
                                "recall_min_ev_abs",
                                "recall_min_ev_rel",
                                "min_pending",
                                "max_flushes_per_day",
                                "enable_reflect",
                                "max_episodes",
                            )
                        },
                    }
                )
            if (
                not plugin.ready
                or plugin.db is None
                or plugin.cache is None
                or plugin.graph is None
            ):
                return error_response(
                    "记忆引擎不可用，请检查运行检测与日志", status_code=503
                )
            service = ManagementService(
                plugin.db, plugin.cache, plugin.graph, plugin._c
            )
            if action == "records":
                return json_response({"records": service.catalog()})
            if action == "detail":
                return json_response(service.detail(request.query.get("id", "")))
            if len(await request.body()) > 65536:
                return error_response("请求内容过大", status_code=413)
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("JSON object required")
            if action == "diagnose":
                result = service.diagnose(body)
                plugin.journal.record(
                    "diagnose", "info", "Read-only recall preview completed"
                )
                return json_response(result)
            if action == "update":
                if plugin.jobs.task is not None and not plugin.jobs.task.done():
                    return error_response("维护任务运行中，请稍后编辑", status_code=409)
                node_id = service.update(body)
                plugin.journal.record(
                    "edit", "succeeded", f"Artifact revised: {node_id}"
                )
                return json_response({"id": node_id})
            if body.get("confirmed") is not True:
                raise ValueError("Confirmation required")
            if action == "cancel":
                if (
                    body.get("id") != plugin.jobs.task_id
                    or plugin.jobs.task is None
                    or plugin.jobs.task.done()
                ):
                    return error_response("任务已结束或不存在", status_code=409)
                plugin.jobs.task.cancel()
                return json_response({"id": plugin.jobs.task_id})
            kind = body.get("kind")
            if not isinstance(kind, str) or kind not in {"extract", "weekly"}:
                raise ValueError("Unknown task")
            operation = plugin._nightly if kind == "extract" else plugin._weekly
            return json_response({"id": plugin.jobs.submit(kind, operation)})
        except LookupError:
            return error_response("记忆不存在，请刷新列表", status_code=404)
        except ValueError as exc:
            if str(exc) == "revision_conflict":
                return error_response(
                    "记忆已被修改，请重新加载后再保存", status_code=409
                )
            return error_response(f"校验失败：{exc}", status_code=400)
        except RuntimeError:
            return error_response("任务正在运行或插件正在停止", status_code=409)
        except Exception as exc:
            plugin.journal.record("webui", "failed", type(exc).__name__)
            return error_response("操作失败，请查看插件日志", status_code=500)
