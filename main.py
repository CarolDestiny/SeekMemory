"""SeekMemory 插件入口。

只做三件事：
1. 把 AstrBot 的事件桥接给 core（不写业务逻辑）
2. 定时触发夜间抽取与每周整理
3. 全程 fail-open —— 记忆系统出任何问题都不能影响正常聊天
"""

from __future__ import annotations

import asyncio
import datetime
import json
import time
from pathlib import Path

from astrbot.api import logger, star
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

from .app.budget import budget_from_config
from .orchestration.access import AccessPolicy
from .orchestration.background_tasks import BackgroundTasks
from .orchestration.capacity_service import CapacityService
from .orchestration.ingest_service import IngestService
from .orchestration.maintenance_service import MaintenanceService
from .orchestration.recall_service import RecallService
from .orchestration.status_service import StatusService
from .app.checkpoint import CheckpointManager
from .app.contracts import DialogueTurn
from .app.dream import DreamCycle
from .app.runtime import (
    AgentRuntime,
    DBEpisodeStore,
    DBStateStore,
    EpisodeRecorder,
    JsonStateStore,
    JsonlEpisodeStore,
    MemoryContext,
    RunContext,
    RunRecorder,
    RuntimeInput,
    RuntimeWorker,
    Scheduler,
    ToolPolicy,
)
from .app.runtime.tracing import RunTracer
from .store.run_trace import TraceStore
from .core.capacity import (
    CapacityGovernor,
    CapacityThresholds,
    load_thresholds,
)
from .core.graph import Graph
from .core.tree import Tree
from .perceive.buffer import Buffer
from .perceive.calls import log_call
from .recall.retriever import HybridRetriever
from .adapters.astrbot_actions import AstrBotActionPort
from .adapters.astrbot_model import AstrBotModelGateway
from .adapters.astrbot_runtime import AstrBotRuntimeAdapter
from .adapters.seekmemory_context import SeekMemoryContextAdapter
from .store.cache import Cache
from .store.db import DB
from .webui.jobs import Jobs
from .webui.journal import Journal
from .webui.routes import WebRoutes
from .webui.trace import Trace


class Main(star.Star):
    def __init__(self, context: star.Context, config: dict | None = None) -> None:
        super().__init__(context, config)
        self.context = context
        self.cfg = config or {}
        self.ready = False
        self.db: DB | None = None
        self.cache: Cache | None = None
        self.tree: Tree | None = None
        self.graph: Graph | None = None
        self.hybrid_retriever: HybridRetriever | None = None
        self.buffer: Buffer | None = None
        self.checkpoint: CheckpointManager | None = None
        self.budget = budget_from_config(self._c)
        self.dream: DreamCycle | None = None
        self.data_path = (
            Path(str(self._c("db_path", ""))).expanduser()
            if self._c("db_path", "")
            else Path(get_astrbot_plugin_data_path()) / "seekmemory" / "memory.db"
        )
        self.journal = Journal(self.data_path.parent / "lifecycle.jsonl")
        self.trace = Trace()
        self.run_traces = TraceStore(
            self.data_path.parent / "run_traces.jsonl",
            retention_days=self._c("trace_retention_days", 7),
            max_rows=self._c("trace_max_rows", 5000),
        )
        self.run_tracer = RunTracer(self.run_traces)
        self.tool_policy = ToolPolicy(
            allowed_prefixes=("memory_", "search_memory", "query_memory")
        )
        self.actions = AstrBotActionPort(context)
        self.jobs = Jobs(self.journal)
        artifact_limit = max(1, int(self._c("max_episodes", 500)))
        self.capacity = CapacityGovernor(self._thresholds(artifact_limit))
        self._last_context_chars = 0
        self._last_runtime_prune_at = 0.0
        self._init_engine()
        self.recall = RecallService(
            cache=self.cache,
            graph=self.graph,
            db=self.db,
            budget=self.budget,
            config=self._c,
            owner_umo=lambda: self.owner_umo,
            hybrid_retriever=self.hybrid_retriever,
            log=lambda msg: logger.info(f"[seekmemory] {msg}"),
        )
        if self.db is not None:
            state_store = DBStateStore(self.db)
            self.episode_recorder = EpisodeRecorder(DBEpisodeStore(self.db))
        else:
            state_store = JsonStateStore(
                str(self.data_path.parent / "runtime_state.json")
            )
            self.episode_recorder = EpisodeRecorder(
                JsonlEpisodeStore(str(self.data_path.parent / "runtime_episodes.jsonl"))
            )
        self.recorder = RunRecorder(
            db=self.db,
            buffer=self.buffer,
            checkpoint=self.checkpoint,
            episodes=self.episode_recorder,
            cache=self.cache,
        )
        self.runtime = AgentRuntime(
            state_store,
            trace=self.trace,
            clock=time.time,
            memory_context=SeekMemoryContextAdapter(self._runtime_memory_context),
            wait_seconds=(
                int(self._c("runtime_wait_seconds", 5))
                if bool(self._c("runtime_gate_enabled", False)) else 0
            ),
            model_gateway=AstrBotModelGateway(context),
            message_sender=self.actions,
            recorder=self.recorder,
        )
        if self.db is not None:
            try:
                self.db.prune_runtime_episodes(
                    retention_days=int(self._c("runtime_episode_retention_days", 30)),
                    max_rows=int(self._c("runtime_episode_max_rows", 5000)),
                )
            except Exception:
                pass
            self._last_runtime_prune_at = time.time()
            self.dream = DreamCycle(
                self.db, self._c,
                log=lambda msg: logger.info(f"[seekmemory] {msg}"),
            )
        self.scheduler = Scheduler(self.runtime.store)
        self.capacity_service = CapacityService(
            db=self.db,
            cache=self.cache,
            trace=self.trace,
            journal=self.journal,
            governor=self.capacity,
            config=self._c,
            logger=logger,
            on_release=self._reload_buffer,
        )
        self.ingest = IngestService(
            buffer=self.buffer,
            db=self.db,
            cache=self.cache,
            graph=self.graph,
            journal=self.journal,
            config=self._c,
            provider_for=context.get_using_provider_async,
            owner_id=lambda: (
                self.owner_umo.split(":")[-1] if self.owner_umo else ""
            ),
            logger=logger,
        )
        self.maintenance = MaintenanceService(
            db=self.db,
            cache=self.cache,
            journal=self.journal,
            task_id=lambda: self.jobs.task_id,
            logger=logger,
        )
        self.status = StatusService(db=self.db)
        self.runtime_worker = RuntimeWorker(
            runtime=self.runtime,
            scheduler=self.scheduler,
            enabled=lambda: bool(self._c("runtime_gate_enabled", False)),
            session_ids=lambda limit: (
                self.db.list_runtime_state_sessions(limit=limit)
                if self.db is not None else []
            ),
            run_context=self._make_run_context,
            interval_seconds=lambda: float(self._c("runtime_tick_seconds", 5)),
            max_attempts=lambda: int(self._c("runtime_dispatch_max_attempts", 3)),
            base_seconds=lambda: float(self._c("runtime_dispatch_backoff_seconds", 2)),
        )
        self.background = BackgroundTasks(
            jobs=self.jobs,
            checkpoint=self.checkpoint,
            buffer=self.buffer,
            capacity=self.capacity_service,
            ingest=self.ingest,
            maintenance=self.maintenance,
            dream=self.dream,
            runtime_worker=self.runtime_worker,
            journal=self.journal,
            config=self._c,
            logger=logger,
        )
        self.web = WebRoutes(self)
        self.web.register()

    # ---------------- 配置 ----------------
    def _c(self, key: str, default):
        try:
            v = self.cfg.get(key, default)
            if v is None:
                return default
            return type(default)(v)
        except Exception:
            return default

    def _maybe_prune_runtime_episodes(self) -> None:
        """Keep runtime audit bounded without doing work on every message."""
        if self.db is None:
            return
        now = time.time()
        if now - self._last_runtime_prune_at < 60:
            return
        try:
            self.db.prune_runtime_episodes(
                retention_days=int(self._c("runtime_episode_retention_days", 30)),
                max_rows=int(self._c("runtime_episode_max_rows", 5000)),
            )
            self._last_runtime_prune_at = now
        except Exception:
            pass

    def _threshold_overrides(self) -> dict:
        """Read ``capacity_thresholds`` as a dict or a JSON object string."""
        raw = self.cfg.get("capacity_thresholds", "")
        if isinstance(raw, dict):
            return raw
        try:
            data = json.loads(str(raw or "").strip() or "{}")
        except (TypeError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _thresholds(self, artifact_limit: int) -> CapacityThresholds:
        """Build capacity limits from defaults, config overrides and env keys."""
        values = dict(self._threshold_overrides())
        values.setdefault("artifact_pressured_count", max(1, int(artifact_limit * 0.8)))
        values.setdefault("artifact_saturated_count", max(1, artifact_limit))
        return load_thresholds(values)

    def _admit_deferred(self) -> bool:
        return self.capacity_service.admit_deferred()

    @property
    def owner_umo(self) -> str:
        return str(self._c("owner_umo", ""))

    @property
    def trusted_ids(self) -> set[str]:
        raw = str(self._c("trusted", ""))
        return {x.strip() for x in raw.replace("，", ",").split(",") if x.strip()}

    # ---------------- 初始化 ----------------
    def _init_engine(self) -> None:
        try:
            self.data_path.parent.mkdir(parents=True, exist_ok=True)
            self.db = DB(str(self.data_path))
            self.cache = Cache(self.db)
            self.cache.load()
            self.tree = Tree(self.db, self.cache)
            self.graph = Graph(self.db, self.cache)
            self.hybrid_retriever = HybridRetriever(self.graph, self.cache)
            self.buffer = Buffer(
                str(self.data_path.parent / "pending.json"), db=self.db
            )
            migrated = self.buffer.migrate_legacy()
            if self.buffer.load_error:
                self.journal.record(
                    "capacity",
                    "warning",
                    "pending file was quarantined",
                    context={"error": self.buffer.load_error},
                )
            self.ready = True
            self.checkpoint = CheckpointManager(
                self.db, self.cache, int(self._c("checkpoint_seconds", 1800))
            )
            self.journal.record(
                "plugin", "ready", f"已加载 {self.cache.size()} 条有效记忆"
            )
            if migrated:
                self.journal.record(
                    "capacity",
                    "info",
                    "旧 pending 已迁移为 Source 投影",
                    context={"rows": migrated},
                )
            logger.info(
                f"[seekmemory] 已加载 {self.cache.size()} 条记忆，"
                f"待抽取 {len(self.buffer.items)} 条"
            )
        except Exception as e:  # noqa: BLE001
            self.journal.record("plugin", "failed", "记忆引擎初始化失败", error=e)
            logger.error(f"[seekmemory] 初始化失败，记忆功能降级：{e}")

    # ---------------- 权限 ----------------
    def _access_policy(self) -> AccessPolicy:
        return AccessPolicy(
            mode=str(self._c("open_to", "owner_only")),
            owner_umo=self.owner_umo,
            trusted_ids=frozenset(self.trusted_ids),
            observe_groups=bool(self._c("observe_groups", True)),
        )

    def _may_remember(self, event: AstrMessageEvent) -> bool:
        return self._access_policy().may_remember(
            str(getattr(event, "unified_msg_origin", "") or ""),
            str(event.get_sender_id()),
        )

    def _group_chat(self, event: AstrMessageEvent) -> bool:
        return AccessPolicy.is_group(
            str(getattr(event, "unified_msg_origin", "") or "")
        )

    def _may_observe(self, event: AstrMessageEvent) -> bool:
        return self._access_policy().may_observe(
            str(getattr(event, "unified_msg_origin", "") or ""),
            str(event.get_sender_id()),
        )

    def _may_recall(self, event: AstrMessageEvent) -> bool:
        return self._access_policy().may_recall(
            str(getattr(event, "unified_msg_origin", "") or ""),
            str(event.get_sender_id()),
        )

    @filter.on_llm_request()
    async def inject_memory(self, event: AstrMessageEvent, req) -> None:
        trace_allowed = False
        trace_info = None
        trace_status = "unknown"
        try:
            if not self._may_recall(event):
                return
            trace_allowed = True
            if not self.ready or self.cache is None:
                return
            text = (event.message_str or "").strip()
            if not text:
                return

            umo = str(getattr(event, "unified_msg_origin", "") or "")
            policy = getattr(self, "tool_policy", None)
            removed_tools = ()
            if bool(self._c("runtime_tool_filter_enabled", False)) and policy is not None:
                removed_tools = policy.filter_tool_set(
                    getattr(req, "func_tool", None)
                )
            if removed_tools:
                self.trace.record(
                    "tool", "guard_removed",
                    {"count": len(removed_tools), "enforced": True},
                )
                self.journal.record(
                    "tool", "info", "runtime tool guard removed tools",
                    context={"removed": len(removed_tools), "enforced": True},
                )
            runtime_input = AstrBotRuntimeAdapter.from_event(
                event, text, umo, str(event.get_sender_id())
            )
            context = self.runtime.build_context(runtime_input)
            block, info = context.text, context.info
            self._last_context_chars = len(block)
            capacity_service = getattr(self, "capacity_service", None)
            if capacity_service is not None:
                capacity_service.set_context_chars(len(block))
            log_call(self._calls_path(), umo, info)
            AstrBotRuntimeAdapter.set_recall_ids(
                event, info.get("final_ids", ())
            )
            self.journal.record(
                "recall",
                "info",
                "召回文本已组装",
                stage="assemble",
                context={key: info[key] for key in ("mode", "picked", "chars")},
            )
            if block:
                # 给记忆块加个明确的框：模型才知道这些是"自己记得的事"，
                # 而不是散落在系统提示里的匿名文本。
                framed = (
                    "\n\n【你的记忆】\n"
                    "下面是你自己记得的事，来自你的记忆库。自然带出来，别逐条复述，"
                    "也别说「根据记忆」。没有这一段，就说明你此刻没想起来。\n"
                    + block
                    + "\n"
                )
                req.system_prompt = (req.system_prompt or "") + framed
                if self._c("debug_log", False):
                    logger.info(f"[seekmemory] 注入 {len(block)} 字")
            trace_info, trace_status = info, "ok"
        except Exception as e:  # noqa: BLE001
            trace_status = "error"
            self.journal.record("recall", "failed", "召回失败", error=e)
            logger.error(f"[seekmemory] 注入失败（不影响回复）：{e}")
        finally:
            if trace_allowed:
                self.run_tracer.request(event, trace_info, trace_status)

    def _runtime_memory_context(self, event: RuntimeInput) -> MemoryContext:
        block, info = self._recall_block(
            event.text, event.session_id, event.private, event.speaker_id
        )
        return MemoryContext(text=block, info=info)

    def _calls_path(self) -> str:
        """调用日志路径：和数据目录放一起。"""
        return str(self.data_path.parent / "calls.jsonl")

    def _recall_block(
        self, text: str, umo: str = "", private: bool = False, speaker: str = ""
    ) -> tuple[str, dict]:
        return self.recall.build(
            text,
            umo,
            private,
            speaker,
            degraded=self._degrade_recall,
        )

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def buffer_message(self, event: AstrMessageEvent) -> None:
        try:
            if not self._may_observe(event):
                return
            text = (event.message_str or "").strip()
            if not text or self.buffer is None:
                return
            umo = str(getattr(event, "unified_msg_origin", "") or "")
            sender = str(event.get_sender_id())
            runtime_input = AstrBotRuntimeAdapter.from_event(
                event,
                text,
                umo,
                sender,
                unread_count=len(self.buffer.items),
            )
            receipt = self.runtime.accept_user(
                runtime_input,
                event_id=AstrBotRuntimeAdapter.event_id(event),
                deferred=self._admit_deferred(),
            )
            if self.buffer.save_error:
                self.journal.record(
                    "capacity",
                    "warning",
                    "pending save failed",
                    context={"error": self.buffer.save_error},
                )
            try:
                self._self_id = str(event.get_self_id())
            except Exception:
                pass
            AstrBotRuntimeAdapter.bind_user(event, receipt)
            AstrBotRuntimeAdapter.apply_decision(event, receipt.decision)
            AstrBotRuntimeAdapter.apply_llm_gate(
                event,
                receipt.decision,
                bool(self._c("runtime_gate_enabled", False)),
            )
        except Exception:
            pass

    @filter.on_llm_response()
    async def capture_reply(self, event: AstrMessageEvent, response) -> None:
        try:
            if self._may_observe(event):
                self.run_tracer.response(
                    event,
                    "error" if getattr(response, "role", "") == "err" else "ok",
                )
            if not self._may_observe(event) or self.db is None:
                return
            if str(getattr(response, "role", "assistant")) == "err":
                return
            text = str(getattr(response, "completion_text", "") or "").strip()
            if not text:
                return
            reply = self.runtime.record_reply(
                run_id=self.run_tracer.run_id(event),
                session_id=str(getattr(event, "unified_msg_origin", "") or ""),
                text=text,
                speaker_id=str(event.get_self_id()),
                turn_id=AstrBotRuntimeAdapter.turn_id(event),
                reply_to=AstrBotRuntimeAdapter.user_source_id(event),
                at=datetime.datetime.now().isoformat(timespec="seconds"),
                recall_ids=AstrBotRuntimeAdapter.recall_ids(event),
            )
            if reply is not None:
                AstrBotRuntimeAdapter.bind_reply(event, reply)
        except Exception:
            pass

    @filter.after_message_sent()
    async def record_delivery(self, event) -> None:
        if self._may_observe(event):
            self.run_tracer.delivered(event)
        if not self._may_observe(event) or self.db is None:
            return
        assistant_source_id = AstrBotRuntimeAdapter.assistant_source_id(event)
        if not assistant_source_id:
            return
        if AstrBotRuntimeAdapter.episode_recorded(event):
            return
        self.runtime.record_delivery(
            run_id=self.run_tracer.run_id(event),
            session_id=str(getattr(event, "unified_msg_origin", "") or ""),
            decision=AstrBotRuntimeAdapter.runtime_action(event),
            reason=AstrBotRuntimeAdapter.runtime_reason(event),
            response_chars=AstrBotRuntimeAdapter.reply_chars(event),
            tool_calls=AstrBotRuntimeAdapter.tool_calls(event),
            user_source_id=AstrBotRuntimeAdapter.user_source_id(event),
            assistant_source_id=assistant_source_id,
        )
        AstrBotRuntimeAdapter.mark_episode_recorded(event)
        self._maybe_prune_runtime_episodes()

    @filter.on_agent_begin()
    async def observe_agent_begin(self, event, run_context) -> None:
        if self._may_observe(event):
            self.run_tracer.begin(event)
        self.trace.record(
            "runtime",
            "agent_begin",
            {
                "decision": AstrBotRuntimeAdapter.runtime_action(event),
                "reason": AstrBotRuntimeAdapter.runtime_reason(event),
            },
        )

    @filter.on_agent_done()
    async def observe_agent_done(self, event, run_context, response) -> None:
        role = str(getattr(response, "role", "") or "")
        if self._may_observe(event):
            self.run_tracer.done(event, "error" if role == "err" else "ok")
        self.trace.record("runtime", "agent_done", {"role": role})
        if role != "err":
            return
        self.runtime.record_error(
            run_id=self.run_tracer.run_id(event),
            session_id=str(getattr(event, "unified_msg_origin", "") or ""),
            decision=AstrBotRuntimeAdapter.runtime_action(event),
            reason=AstrBotRuntimeAdapter.runtime_reason(event),
            error="agent_error",
            user_source_id=AstrBotRuntimeAdapter.user_source_id(event),
        )
        self._maybe_prune_runtime_episodes()

    @filter.on_using_llm_tool()
    async def observe_tool(self, event, tool, tool_args) -> None:
        if self._may_observe(event):
            self.run_tracer.tool_begin(event, tool)
        call = AstrBotRuntimeAdapter.observe_tool(
            event, tool, tool_args, self.tool_policy
        )
        self.trace.record(
            "tool",
            "allowed" if call.allowed else "advisory_denied",
            {
                "tool": call.name,
                "argKeys": len(call.args_keys),
                "enforced": False,
            },
        )

    @filter.on_llm_tool_respond()
    async def observe_tool_result(self, event, tool, tool_args, tool_result) -> None:
        if self._may_observe(event):
            self.run_tracer.tool_end(event, tool)
        name = str(getattr(tool, "name", tool) or "")
        self.trace.record(
            "tool",
            "result",
            {"tool": name, "ok": bool(tool_result)},
        )

    @filter.on_astrbot_loaded()
    @property
    def _schedulers(self) -> list[asyncio.Task]:
        return self.background.tasks

    @property
    def _flushing(self) -> bool:
        return bool(getattr(self, "ingest", None) and self.ingest.flushing)

    @property
    def _flush_count(self) -> int:
        return int(getattr(self, "ingest", None).flush_count) if getattr(self, "ingest", None) else 0

    @property
    def _degrade_recall(self) -> bool:
        service = getattr(self, "capacity_service", None)
        return bool(service and service.degrade_recall)

    async def start_jobs(self) -> None:
        if not self.ready or self.jobs.closed or self.background.tasks:
            return
        self.background.start()

    async def initialize(self) -> None:
        await self.start_jobs()

    async def terminate(self) -> None:
        self.ready = False
        await self.background.stop()
        await self.jobs.close()
        self.web.close()
        if self.buffer is not None:
            self.buffer.save()
        if self.checkpoint is not None:
            self.checkpoint.flush()
        if self.db is not None:
            self.db.close()
            self.db = None
        self.journal.record("plugin", "stopped", "plugin resources released")

    async def _checkpoint_loop(self) -> None:
        await self.background._checkpoint_loop()

    async def _nightly_loop(self) -> None:
        await self.background._nightly_loop()

    async def _weekly_loop(self) -> None:
        await self.background._weekly_loop()

    @staticmethod
    def _seconds_until(hhmm: str, weekday: int | None = None) -> float:
        return BackgroundTasks.seconds_until(hhmm, weekday)

    def _reload_buffer(self) -> None:
        if self.buffer is not None:
            self.buffer.reload()

    def _capacity_snapshot(self):
        return self.capacity_service.snapshot()

    @staticmethod
    def _json_object(raw: object) -> dict:
        return StatusService.json_object(raw)

    @classmethod
    def _header_evidence(cls, raw_header: object) -> tuple[list[str], list[str]]:
        return StatusService.header_evidence(raw_header)

    def persona_status(self) -> dict | None:
        return self.status.persona()

    def capacity_status(self) -> dict:
        return self.capacity_service.status()

    def _observe_capacity(self):
        return self.capacity_service.observe()

    def _apply_capacity_maintenance(self, decision) -> None:
        self.capacity_service.apply_maintenance(decision)

    def _batch_cap(self, decision) -> int:
        return self.capacity_service.batch_cap(decision)

    def _should_flush(self, capacity=None) -> bool:
        return self.background.should_flush()

    @property
    def _dream_on(self) -> bool:
        return bool(self.dream is not None and self.dream.enabled)

    def _make_run_context(self, session_id: str, now: float) -> RunContext:
        source = self.db.latest_user_source(session_id) if self.db is not None else None
        source = source or {}
        return RunContext(
            session_id=session_id,
            text=str(source.get("text") or "").strip(),
            source_id=str(source.get("id") or ""),
            bot_id=str(getattr(self, "_self_id", "") or "bot"),
            at=now,
        )

    async def _runtime_scheduler_tick(self) -> None:
        await self.runtime_worker.tick()

    async def _dispatch_deferred(self, session_id: str, now: float) -> None:
        await self.runtime_worker.dispatch(session_id, now)

    async def _runtime_loop(self) -> None:
        await self.runtime_worker.run_forever()

    async def _idle_loop(self) -> None:
        await self.background._idle_loop()

    async def _ingest_loop(self) -> None:
        await self.background._ingest_loop()

    async def _dream_loop(self) -> None:
        await self.background._dream_loop()

    async def _run_dream(self) -> None:
        await self.background.run_dream()

    async def _dream_maintain(self) -> dict:
        return await self.background.dream_maintain()

    async def _nightly(self) -> None:
        await self.background.nightly()

    def _split_topics(self, items: list[DialogueTurn], cap: int | None = None):
        return self.ingest.split_topics(items, cap)

    async def _flush(self, reason: str, limit: int = 0) -> tuple[int, int]:
        return await self.background.flush(reason, limit)

    async def _weekly(self) -> dict:
        return await self.background.weekly()
