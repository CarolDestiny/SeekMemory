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
from functools import partial
from pathlib import Path

from astrbot.api import logger, star
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

from .app.budget import budget_from_config, estimate_tokens
from .app.checkpoint import CheckpointManager
from .app.contracts import DialogueTurn
from .app.dream import DreamCycle
from .app.flush_policy import chunk_turns, decide_flush, select_topic_batches
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
    Scheduler,
    ToolPolicy,
)
from .app.runtime.tracing import RunTracer
from .store.run_trace import TraceStore
from .core.capacity import (
    NORMAL,
    PROTECTIVE,
    SATURATED,
    CapacityDecision,
    CapacityGovernor,
    CapacitySnapshot,
    CapacityThresholds,
    load_thresholds,
)
from .core.graph import Graph
from .core.source import Source, make_source_id
from .core.tree import Tree
from .perceive.absorb import absorb, worth_now
from .perceive.buffer import Buffer
from .perceive.calls import log_call
from .perceive.model import ProviderChatModel
from .recall.pipeline import build_block
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
        self._flushing = False
        self._flush_day = ""
        self._flush_count = 0
        self.budget = budget_from_config(self._c)
        self.dream: DreamCycle | None = None
        self._schedulers: list[asyncio.Task] = []
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
        self._capacity_state = NORMAL
        self._capacity_action_mark = ""
        self._degrade_recall = False
        self._last_context_chars = 0
        self._backpressure = False
        self._deferred_rows = 0
        self._last_runtime_prune_at = 0.0
        self._runtime_dispatching: set[str] = set()
        self._runtime_tick_lock = asyncio.Lock()
        self._init_engine()
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
        self.scheduler = Scheduler(self.runtime.store)
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
        """Park new extraction work while capacity admission is closed."""
        if not self._backpressure:
            return False
        return self._deferred_rows < self.capacity.thresholds.defer_limit

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
    def _may_remember(self, event: AstrMessageEvent) -> bool:
        """私聊侧的记忆权限（沿用 open_to 配置）。"""
        mode = str(self._c("open_to", "owner_only"))
        if mode == "everyone":
            return True
        umo = getattr(event, "unified_msg_origin", "")
        if umo == self.owner_umo:
            return True
        if mode == "owner_and_trusted":
            sid = str(event.get_sender_id())
            return sid in self.trusted_ids or umo == self.owner_umo
        return False

    def _group_chat(self, event: AstrMessageEvent) -> bool:
        """是不是群聊消息。"""
        umo = str(getattr(event, "unified_msg_origin", "") or "")
        return ":GroupMessage:" in umo

    def _may_observe(self, event: AstrMessageEvent) -> bool:
        """能不能把这句话记下来：私聊按 open_to，群聊按 observe_groups。"""
        if self._may_remember(event):
            return True
        return bool(self._c("observe_groups", True)) and self._group_chat(event)

    def _may_recall(self, event: AstrMessageEvent) -> bool:
        """能不能给她注入记忆：主人私聊 + 观察中的群；别人的私聊不注入。"""
        return self._may_observe(event)

    # ---------------- 读路径：注入 ----------------
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
            log_call(self._calls_path(), umo, info)
            event.set_extra(
                "_seekmemory_recall_ids",
                tuple(str(item) for item in info.get("final_ids", ())),
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
        """交给读路径模块：常驻层 + 检索 + 偶然浮现。"""
        budget_chars = int(self.budget.injection_chars)
        recall_k = int(self._c("recall_k", 8))
        if self._degrade_recall:  # 容量紧张时减半
            budget_chars = max(80, budget_chars // 2)
            recall_k = max(1, recall_k // 2)

        def conf(key: str, default):
            """把预算注入到读路径配置里，其它键仍走插件配置。"""
            if key == "budget_chars":
                return budget_chars
            if key == "recall_k":
                return recall_k
            return self._c(key, default)

        return build_block(
            self.cache,
            self.graph,
            self.db,
            umo,
            text,
            private,
            conf,
            self.owner_umo,
            speaker,
            log=lambda msg: logger.info(f"[seekmemory] {msg}"),
            hybrid_retriever=self.hybrid_retriever,
        )

    # ---------------- 写路径：缓冲 ----------------
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
            event_id = str(
                getattr(getattr(event, "message_obj", None), "message_id", "") or ""
            )
            now = datetime.datetime.now().isoformat(timespec="seconds")
            source_id = make_source_id(
                event_id=event_id,
                session_id=umo,
                speaker_id=sender,
                role="user",
                text=text,
                at=now,
            )
            turn_id = event_id or source_id
            source = Source(source_id, turn_id, umo, sender, "user", text, now)
            self.buffer.add(
                umo,
                text,
                sender,
                source_id,
                now,
                source=source,
                turn_id=turn_id,
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
            event.set_extra("_seekmemory_turn_id", turn_id)
            event.set_extra("_seekmemory_source_id", source_id)
            decision = self.runtime.observe(
                AstrBotRuntimeAdapter.from_event(
                    event, text, umo, sender, unread_count=len(self.buffer.items)
                )
            )
            AstrBotRuntimeAdapter.apply_decision(event, decision)
            AstrBotRuntimeAdapter.apply_llm_gate(
                event, decision, bool(self._c("runtime_gate_enabled", False))
            )
        except Exception:
            pass

    @filter.on_llm_response()
    async def capture_reply(self, event: AstrMessageEvent, response) -> None:
        try:
            if self._may_observe(event):
                self.run_tracer.response(
                    event, "error" if getattr(response, "role", "") == "err" else "ok"
                )
            if not self._may_observe(event) or self.db is None:
                return
            if str(getattr(response, "role", "assistant")) == "err":
                return
            text = str(getattr(response, "completion_text", "") or "").strip()
            if not text:
                return
            umo = str(getattr(event, "unified_msg_origin", "") or "")
            turn_id = str(event.get_extra("_seekmemory_turn_id", "") or "")
            if not turn_id:
                turn_id = make_source_id(
                    session_id=umo,
                    speaker_id=str(event.get_sender_id()),
                    role="assistant",
                    text=text,
                )
            reply = self.recorder.record_reply(
                run_id=self.run_tracer.run_id(event),
                session_id=umo,
                text=text,
                speaker_id=str(event.get_self_id()),
                turn_id=turn_id,
                reply_to=str(event.get_extra("_seekmemory_source_id", "") or ""),
                at=datetime.datetime.now().isoformat(timespec="seconds"),
                recall_ids=event.get_extra("_seekmemory_recall_ids", ()) or (),
            )
            event.set_extra("_seekmemory_turn_id", reply.turn_id)
            event.set_extra(
                "_seekmemory_assistant_source_id", reply.assistant_source_id
            )
            event.set_extra("_seekmemory_reply_chars", reply.response_chars)
            event.set_extra("_seekmemory_recall_ids", ())
        except Exception:
            pass

    @filter.after_message_sent()
    async def record_delivery(self, event) -> None:
        if self._may_observe(event):
            self.run_tracer.delivered(event)
        if not self._may_observe(event) or self.db is None:
            return
        assistant_source_id = str(
            event.get_extra("_seekmemory_assistant_source_id", "") or ""
        )
        if not assistant_source_id:
            return
        if event.get_extra("_seekmemory_episode_recorded", False):
            return
        umo = str(getattr(event, "unified_msg_origin", "") or "")
        self.runtime.mark_delivered(umo)
        self.recorder.record_delivery(
            run_id=self.run_tracer.run_id(event),
            session_id=umo,
            decision=str(event.get_extra("_seekmemory_runtime_action", "") or "observe"),
            reason=str(event.get_extra("_seekmemory_runtime_reason", "") or ""),
            response_chars=int(event.get_extra("_seekmemory_reply_chars", 0) or 0),
            tool_calls=event.get_extra("_seekmemory_tool_calls", ()) or (),
            user_source_id=str(event.get_extra("_seekmemory_source_id", "") or ""),
            assistant_source_id=assistant_source_id,
        )
        event.set_extra("_seekmemory_episode_recorded", True)
        self._maybe_prune_runtime_episodes()

    @filter.on_agent_begin()
    async def observe_agent_begin(self, event, run_context) -> None:
        if self._may_observe(event):
            self.run_tracer.begin(event)
        self.trace.record(
            "runtime",
            "agent_begin",
            {
                "decision": str(event.get_extra("_seekmemory_runtime_action", "") or ""),
                "reason": str(event.get_extra("_seekmemory_runtime_reason", "") or ""),
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
        self.recorder.record_error(
            run_id=self.run_tracer.run_id(event),
            session_id=str(getattr(event, "unified_msg_origin", "") or ""),
            decision=str(event.get_extra("_seekmemory_runtime_action", "") or "observe"),
            reason=str(event.get_extra("_seekmemory_runtime_reason", "") or ""),
            error="agent_error",
            user_source_id=str(event.get_extra("_seekmemory_source_id", "") or ""),
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
    async def start_jobs(self) -> None:
        if not self.ready or self.jobs.closed or self._schedulers:
            return
        operations = [
            self._weekly_loop,
            self._checkpoint_loop,
            self._dream_loop,
            self._runtime_loop,
        ]
        if self._dream_on:
            # 白天也要批量入库：只抽取、不进化，进化留给 dream。
            operations.append(self._ingest_loop)
        else:  # 兼容旧行为：梦境关掉才保留白天/夜间抽取
            operations += [self._nightly_loop, self._idle_loop]
        self._schedulers = [
            asyncio.create_task(operation()) for operation in operations
        ]
        self.journal.record("scheduler", "running", "维护定时任务已启动")

    async def initialize(self) -> None:
        """插件激活时启动定时任务，兼容热重载。"""
        await self.start_jobs()

    async def terminate(self) -> None:
        """依次取消本实例任务、移除路由并关闭存储。"""
        self.ready = False
        for task in self._schedulers:
            task.cancel()
        await asyncio.gather(*self._schedulers, return_exceptions=True)
        self._schedulers.clear()
        await self.jobs.close()
        self.web.close()
        if self.buffer is not None:
            self.buffer.save()
        if self.checkpoint is not None:
            self.checkpoint.flush()
        if self.db is not None:
            self.db.close()
            self.db = None
        self.journal.record("plugin", "stopped", "插件资源已释放")

    async def _checkpoint_loop(self) -> None:
        while True:
            interval = max(60, int(self._c("checkpoint_seconds", 1800)))
            await asyncio.sleep(interval)
            try:
                if self.checkpoint is not None:
                    self.checkpoint.flush()
            except Exception as e:
                logger.error(f"[seekmemory] checkpoint failed: {e}")

    async def _nightly_loop(self) -> None:
        while True:
            await asyncio.sleep(
                self._seconds_until(str(self._c("summary_time", "23:50")))
            )
            try:
                self.jobs.submit("nightly", self._nightly)
            except Exception as e:  # noqa: BLE001
                logger.error(f"[seekmemory] 夜间整理失败：{e}")
                self.journal.record("scheduler", "failed", "定时任务提交失败", error=e)

    async def _weekly_loop(self) -> None:
        while True:
            await asyncio.sleep(
                self._seconds_until("23:55", weekday=self._c("weekly_day", 6))
            )
            try:
                self.jobs.submit("weekly", self._weekly)
            except Exception as e:  # noqa: BLE001
                logger.error(f"[seekmemory] 每周整理失败：{e}")
                self.journal.record("scheduler", "failed", "定时任务提交失败", error=e)

    @staticmethod
    def _seconds_until(hhmm: str, weekday: int | None = None) -> float:
        try:
            hh, mm = (int(x) for x in hhmm.split(":"))
            if not 0 <= hh <= 23 or not 0 <= mm <= 59:
                raise ValueError("定时时间无效")
        except Exception:
            hh, mm = 23, 50
        now = datetime.datetime.now()
        target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if target <= now:
            target += datetime.timedelta(days=1)
        if weekday is not None:
            weekday = int(weekday) % 7
            while target.weekday() != weekday:
                target += datetime.timedelta(days=1)
        return max((target - now).total_seconds(), 60)

    # ---------------- 抽取：空闲触发 + 夜间兜底 ----------------
    def _capacity_snapshot(self) -> CapacitySnapshot:
        """Collect bounded usage metrics without exposing row content."""
        usage = self.db.capacity_usage() if self.db is not None else {}
        trace_rows = self.trace.count
        trace_age = self.trace.oldest_age_seconds()
        return CapacitySnapshot(
            source_rows=int(usage.get("source_rows", 0)),
            source_bytes=int(usage.get("source_bytes", 0)),
            pending_rows=int(usage.get("pending_rows", 0)),
            pending_oldest_age_seconds=float(
                usage.get("pending_oldest_age_seconds", 0.0)
            ),
            deferred_rows=int(usage.get("deferred_rows", 0)),
            dead_rows=int(usage.get("dead_rows", 0)),
            db_bytes=int(usage.get("db_bytes", 0)),
            artifact_count=int(usage.get("artifact_count", 0)),
            artifact_bytes=int(usage.get("artifact_bytes", 0)),
            expired_artifacts=int(usage.get("expired_artifacts", 0)),
            context_chars_per_turn=self._last_context_chars,
            trace_rows=trace_rows,
            trace_oldest_age_seconds=trace_age,
        )

    @staticmethod
    def _json_object(raw: object) -> dict:
        """Decode one stored JSON object, tolerating nested string history."""
        value = raw
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (TypeError, ValueError):
                return {}
        return value if isinstance(value, dict) else {}

    @classmethod
    def _header_evidence(cls, raw_header: object) -> tuple[list[str], list[str]]:
        """Read a single revision's stored lineage without inheriting the head."""
        header = cls._json_object(raw_header)
        lineage = cls._json_object(header.get("lineage"))

        def ids(*names: str) -> list[str]:
            for name in names:
                value = lineage.get(name)
                if isinstance(value, str):
                    try:
                        value = json.loads(value)
                    except (TypeError, ValueError):
                        continue
                if not isinstance(value, (list, tuple)):
                    continue
                out: list[str] = []
                for item in value:
                    if not isinstance(item, str):
                        continue
                    text = item.strip()
                    if text and text not in out:
                        out.append(text)
                return out
            return []

        return ids("derived_from", "derivedFrom"), ids("sources", "sourceIds")

    def persona_status(self) -> dict | None:
        """Return the current global persona and its revision timeline.

        Each revision carries only the evidence recorded in its own historical
        header. A missing or malformed header yields empty arrays; the current
        head lineage is never copied onto older revisions and source text is
        never exposed here.
        """
        if self.db is None:
            return None
        active = [art for art in self.db.list(family="persona", state="active")]
        if not active:
            return None
        current = max(active, key=lambda art: art.header.revision)
        evidence: dict[int, tuple[list[str], list[str]]] = {}
        inspected = self.db.inspect_record(current.header.id)
        for row in inspected.get("versions", []):
            try:
                revision = int(row.get("revision") or 0)
            except (TypeError, ValueError):
                continue
            evidence[revision] = self._header_evidence(row.get("header"))
        revisions = []
        for row in self.db.history(current.header.id):
            revision = int(row.get("revision") or 0)
            derived_from, source_ids = evidence.get(revision, ([], []))
            payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
            revisions.append({
                "revision": revision,
                "at": str(row.get("at") or ""),
                "op": str(row.get("op") or ""),
                "text": str(payload.get("text") or ""),
                "derivedFrom": list(derived_from),
                "sourceIds": list(source_ids),
            })
        return {
            "id": current.header.id,
            "revision": int(current.header.revision),
            "text": str(current.payload.get("text") or ""),
            "revisions": revisions,
        }

    def capacity_status(self) -> dict:
        """Return a content-free capacity report for the WebUI status endpoint."""
        snapshot = self._capacity_snapshot()
        decision = self.capacity.evaluate(snapshot)
        queue = self.db.queue_counts() if self.db is not None else {}
        return {
            "state": decision.state,
            "actions": list(decision.actions),
            "reasons": list(decision.reasons),
            "pressure": decision.pressure,
            "snapshot": {
                "sourceRows": snapshot.source_rows,
                "sourceBytes": snapshot.source_bytes,
                "pendingRows": snapshot.pending_rows,
                "deferredRows": snapshot.deferred_rows,
                "deadRows": snapshot.dead_rows,
                "databaseBytes": snapshot.db_bytes,
                "artifactCount": snapshot.artifact_count,
                "artifactBytes": snapshot.artifact_bytes,
                "contextChars": snapshot.context_chars_per_turn,
                "traceRows": snapshot.trace_rows,
            },
            "queue": {str(key): int(value) for key, value in queue.items()},
        }

    def _observe_capacity(self) -> CapacityDecision:
        """Evaluate and journal capacity transitions for scheduler decisions."""
        snapshot = self._capacity_snapshot()
        decision = self.capacity.evaluate(snapshot)
        self._degrade_recall = "degrade_recall" in decision.actions
        self._backpressure = "backpressure" in decision.actions
        self._deferred_rows = snapshot.deferred_rows
        if decision.state != self._capacity_state:
            self.journal.record(
                "capacity",
                "warning" if decision.state != NORMAL else "info",
                f"容量状态切换为 {decision.state}",
                stage="governor",
                context={
                    "pending": snapshot.pending_rows,
                    "deferred": snapshot.deferred_rows,
                    "dead": snapshot.dead_rows,
                    "databaseBytes": snapshot.db_bytes,
                    "artifacts": snapshot.artifact_count,
                    "actions": len(decision.actions),
                    "pressure": decision.pressure,
                },
            )
            if decision.state == PROTECTIVE:
                logger.warning("[seekmemory] 容量进入保护状态")
            self.trace.record(
                "capacity",
                decision.state,
                {
                    "pending": snapshot.pending_rows,
                    "deferred": snapshot.deferred_rows,
                    "dead": snapshot.dead_rows,
                    "databaseBytes": snapshot.db_bytes,
                    "pressure": decision.pressure,
                },
            )
            self._capacity_state = decision.state
        return decision

    def _apply_capacity_maintenance(self, decision: CapacityDecision) -> None:
        """Release parked writes on headroom; run lifecycle actions hourly."""
        if ("release_deferred" in decision.actions and self._deferred_rows
                and self.db is not None):
            released = self.db.release_deferred(self.capacity.thresholds.release_batch)
            if released:
                self._deferred_rows = max(0, self._deferred_rows - released)
                if self.buffer is not None:
                    self.buffer.reload()
                self.journal.record(
                    "capacity",
                    "info",
                    "积压写入已重新入队",
                    stage="admission",
                    context={"released": released},
                )
        actions = set(decision.actions)
        actionable = {
            "compact_artifacts",
            "forget_expired",
            "trim_trace",
            "alert",
        }
        if not actionable.intersection(actions):
            return
        mark = datetime.datetime.now().strftime("%Y%m%d%H")
        if mark == self._capacity_action_mark:
            return
        self._capacity_action_mark = mark
        if "compact_artifacts" in actions and self.db and self.cache:
            from .maintain.merge import merge_similar

            with self.journal.span("capacity", "compact_artifacts") as metrics:
                metrics["merged"] = merge_similar(
                    self.db,
                    self.cache,
                    threshold=0.6,
                    limit=50,
                )
        if "forget_expired" in actions and self.db and self.cache:
            from .maintain.lifecycle import forget_expired

            with self.journal.span("capacity", "forget_expired") as metrics:
                metrics["forgotten"] = forget_expired(self.db, self.cache)
        if "trim_trace" in actions:
            with self.journal.span("capacity", "trim_trace") as metrics:
                metrics["removed"] = self.trace.trim(
                    self.capacity.thresholds.trace_pressured_rows
                )
        if "alert" in actions:
            self.journal.record(
                "capacity",
                "warning",
                "容量保护告警",
                stage="governor",
                context={"state": decision.state},
            )
        self.trace.record(
            "maintenance",
            decision.state,
            {"actions": len(actions), "deferred": self._deferred_rows},
        )

    def _batch_cap(self, decision: CapacityDecision) -> int:
        cap = max(1, int(self._c("max_sessions_per_flush", 6)))
        return min(24, cap * 2) if "raise_batch_size" in decision.actions else cap

    def _should_flush(self, capacity: CapacityDecision | None = None) -> bool:
        if self._flushing or self.buffer is None or self.db is None:
            return False
        capacity = capacity or self._observe_capacity()
        today = datetime.date.today().isoformat()
        if self._flush_day != today:
            self._flush_day, self._flush_count = today, 0
        decision = decide_flush(
            pending=len(self.buffer.items),
            idle_seconds=self.buffer.idle_seconds(),
            worth_now=worth_now(self.buffer.items),
            flushes_today=self._flush_count,
            idle_flush_seconds=float(self._c("idle_flush_seconds", 0)),
            min_pending=int(self._c("min_pending", 8)),
            max_flushes_per_day=int(self._c("max_flushes_per_day", 2)),
            backlog_flush_at=int(self._c("backlog_flush_at", 30)),
            topic_age_seconds=self.buffer.oldest_topic_age(),
            topic_ttl_seconds=float(self._c("topic_ttl_seconds", 86400)),
            dream_only=self._dream_on,
        )
        if decision.should:
            return True
        if self._dream_on:
            return False
        return (
            capacity.state in (SATURATED, PROTECTIVE)
            and "schedule_extraction" in capacity.actions
        )

    @property
    def _dream_on(self) -> bool:
        """梦境模式：白天只缓冲，抽取与进化都留到 dream 周期。"""
        return bool(self.dream is not None and self.dream.enabled)

    async def _runtime_scheduler_tick(self) -> None:
        if self.db is None or not bool(self._c("runtime_gate_enabled", False)):
            return
        async with self._runtime_tick_lock:
            now = time.time()
            due = self.scheduler.due(
                self.db.list_runtime_state_sessions(limit=100), now
            )
            for item in due:
                session_id = item.session_id
                if session_id in self._runtime_dispatching:
                    continue
                try:
                    self._runtime_dispatching.add(session_id)
                    try:
                        await self._dispatch_deferred(session_id, now)
                    finally:
                        self._runtime_dispatching.discard(session_id)
                except Exception:
                    continue

    async def _dispatch_deferred(self, session_id: str, now: float) -> None:
        """Generate one deferred group reply after the ambient wait expires."""
        if not bool(self._c("runtime_gate_enabled", False)):
            return
        source = self.db.latest_user_source(session_id) if self.db is not None else None
        source = source or {}
        text = str(source.get("text") or "").strip()
        source_id = str(source.get("id") or "")
        await self.runtime.dispatch_deferred(
            RunContext(
                session_id=session_id,
                text=text,
                source_id=source_id,
                bot_id=str(getattr(self, "_self_id", "") or "bot"),
                at=now,
            ),
            max_attempts=int(self._c("runtime_dispatch_max_attempts", 3)),
            base_seconds=float(self._c("runtime_dispatch_backoff_seconds", 2)),
        )

    async def _runtime_loop(self) -> None:
        while True:
            await asyncio.sleep(max(1, int(self._c("runtime_tick_seconds", 5))))
            try:
                await self._runtime_scheduler_tick()
            except Exception as e:  # noqa: BLE001
                self.journal.record("runtime", "failed", "runtime tick failed", error=e)

    async def _idle_loop(self) -> None:
        """聊完安静一会儿就抽，不用等到半夜。"""
        while True:
            await asyncio.sleep(30)
            try:
                capacity = self._observe_capacity()
                self._apply_capacity_maintenance(capacity)
                await self._runtime_scheduler_tick()
                if self._should_flush(capacity):
                    self.jobs.submit("idle", lambda: self._flush("空闲"))
            except Exception as e:  # noqa: BLE001
                logger.error(f"[seekmemory] 空闲抽取失败：{e}")
                self.journal.record("scheduler", "failed", "定时任务提交失败", error=e)

    async def _ingest_loop(self) -> None:
        """白天批量入库：积压够多就按批抽取，让记忆跟得上聊天。

        和 dream 分工——这里只负责"抽取成记忆"，合并/修订印象/沉淀人格
        仍然只在 dream 里做，避免白天人格漂移。
        """
        while True:
            interval = max(120, int(self._c("ingest_interval_seconds", 600)))
            await asyncio.sleep(interval)
            try:
                if self.buffer is None or not self.buffer.items:
                    continue
                if not self._c("ingest_enabled", True):
                    continue
                if len(self.buffer.items) < int(self._c("ingest_min_pending", 20)):
                    continue
                cap = max(1, int(self._c("ingest_batch_topics", 20)))
                self.jobs.submit("ingest", lambda: self._flush("定时批量", limit=cap))
            except Exception as e:  # noqa: BLE001
                logger.error(f"[seekmemory] 定时批量抽取失败：{e}")

    async def _dream_loop(self) -> None:
        """每天 dream_time 跑一次进化；启动时若已过点且没做，立刻补一次。"""
        if self.dream is not None and self.dream.due():
            try:
                self.jobs.submit("dream", self._run_dream)
            except Exception as e:  # noqa: BLE001
                logger.error(f"[seekmemory] 补跑梦境失败：{e}")
        while True:
            await asyncio.sleep(
                self._seconds_until(str(self._c("dream_time", "03:30")))
            )
            try:
                self.jobs.submit("dream", self._run_dream)
            except Exception as e:  # noqa: BLE001
                logger.error(f"[seekmemory] 梦境任务提交失败：{e}")
                self.journal.record("scheduler", "failed", "梦境提交失败", error=e)

    async def _run_dream(self) -> None:
        """一次梦境：批量抽取当天的缓冲，再做整理与人格沉淀。"""
        if self.dream is None or self.buffer is None:
            return
        self._apply_capacity_maintenance(self._observe_capacity())
        result = await self.dream.run(
            flush_once=self._flush,
            pending=lambda: len(self.buffer.items),
            maintain=self._dream_maintain,
        )
        self.journal.record(
            "dream",
            result.status,
            f"{result.date}：{result.batches} 个话题 / 写入 {result.written} 条"
            + (f" / {len(result.errors)} 个错误" if result.errors else ""),
            self.jobs.task_id,
            context={
                "date": result.date,
                "batches": result.batches,
                "written": result.written,
                "errors": list(result.errors),
            },
        )

    async def _dream_maintain(self) -> dict:
        """抽取之后的整理：遗忘、合并、人格沉淀。"""
        return await self._weekly()

    async def _nightly(self) -> None:
        """夜间兜底：把白天没来得及抽的尾巴抽掉。"""
        self._apply_capacity_maintenance(self._observe_capacity())
        await self._flush("夜间")

    def _split_topics(
        self, items: list[DialogueTurn], cap: int | None = None
    ) -> list[tuple[str, str, list[DialogueTurn]]]:
        """按会话轮询选择话题，保证长会话不会长期独占抽取批次。"""
        return select_topic_batches(
            items, int(cap or self._c("max_sessions_per_flush", 6))
        )

    async def _flush(self, reason: str, limit: int = 0) -> tuple[int, int]:
        """按上游会话与结果契约抽取，处理成功前保留缓冲。

        Args:
            reason: 触发本次抽取的业务原因。

        Raises:
            Exception: 批次结束后传播首个会话失败，供任务执行器记录失败状态。
        """
        if (
            self._flushing
            or self.buffer is None
            or not self.buffer.items
            or self.db is None
        ):
            return 0, 0
        self._flushing = True
        try:
            capacity = self._observe_capacity()
            topics = self._split_topics(
                list(self.buffer.items),
                cap=limit or self._batch_cap(capacity),
            )
            ready_ids = self.db.ready_extraction_ids()
            ready = []
            failure: Exception | None = None
            for umo, topic_id, part in topics:
                part = [
                    turn
                    for turn in part
                    if not turn.source_id or turn.source_id in ready_ids
                ]
                if not part:
                    continue
                try:
                    with self.journal.span(
                        "extract", "provider.resolve", session=umo, topic=topic_id
                    ):
                        prov = await self.context.get_using_provider_async(umo or None)
                except Exception as exc:
                    if self.buffer is not None:
                        self.buffer.mark_failed(
                            part,
                            type(exc).__name__,
                            max_attempts=self.capacity.thresholds.extraction_max_attempts,
                        )
                    failure = failure or exc
                    continue
                if not prov:
                    self.journal.record(
                        "extract",
                        "warning",
                        "该会话尚未配置模型服务，保留待抽取消息",
                        stage="provider.resolve",
                        context={"session": umo, "topic": topic_id},
                    )
                    continue
                ready.append((umo, topic_id, part, prov))
            if not ready:
                if failure is not None:
                    raise failure
                return 0, 0
            self._flush_count += 1
            written = 0
            for umo, topic_id, part, prov in ready:
                for chunk in chunk_turns(part):
                    try:
                        with self.journal.span(
                            "extract",
                            "topic.extract",
                            session=umo,
                            topic=topic_id,
                            messages=len(chunk),
                        ) as metrics:
                            outcome = await absorb(
                                chunk,
                                self.db,
                                self.cache,
                                self.graph,
                                ProviderChatModel(prov),
                                log=partial(self.journal.record, "extract", "warning"),
                                owner_id=self.owner_umo.split(":")[-1]
                                if self.owner_umo
                                else "",
                                strict=True,
                                stage=partial(self.journal.span, "extract"),
                            )
                            metrics["written"] = outcome.written
                            metrics["skipped"] = outcome.skipped
                            if outcome.model_failed or outcome.retryable:
                                raise RuntimeError("extraction failed; keep pending input")
                    except Exception as exc:
                        self.buffer.mark_failed(
                            chunk,
                            type(exc).__name__,
                            max_attempts=self.capacity.thresholds.extraction_max_attempts,
                        )
                        failure = failure or exc
                        break
                    self.buffer.mark_succeeded(chunk)
                    written += outcome.written
                    logger.info(
                        f"[seekmemory] {reason} extract {umo or 'unknown'}: "
                        f"topic {topic_id}, {len(chunk)} turns, {outcome.written} written"
                    )
            self.journal.record(
                "extract",
                "info",
                f"已尝试 {len(ready)} 个话题，写入 {written} 条记忆",
                context={"topics": len(ready), "written": written},
                stage="batch.complete",
            )
            if failure is not None:
                raise failure
            return written, len(ready)
        finally:
            self._flushing = False

    async def _weekly(self) -> dict:
        from .maintain.decay import decay_all
        from .maintain.merge import merge_similar
        from .maintain.persona import distill_self_persona
        from .maintain.self_impression import build_self_impressions

        if self.db is None or self.cache is None:
            return {}
        today = datetime.date.today().isoformat()
        with self.journal.span("weekly", "self_impression") as metrics:
            self_made = build_self_impressions(self.db, self.cache, today=today)
            metrics["made"] = self_made
        with self.journal.span("weekly", "decay") as metrics:
            dropped = decay_all(self.db, self.cache, today)
            metrics["forgotten"] = dropped
        with self.journal.span("weekly", "merge", threshold=0.6) as metrics:
            merged = merge_similar(self.db, self.cache, threshold=0.6)
            metrics["merged"] = merged
        with self.journal.span("weekly", "persona") as metrics:
            persona = distill_self_persona(self.db, self.cache, today)
            metrics["updated"] = bool(persona)
        self.journal.record(
            "weekly",
            "info",
            f"遗忘 {dropped} 条，合并 {merged} 条，人格更新：{bool(persona)}",
            self.jobs.task_id,
        )
        logger.info(
            f"[seekmemory] 每周整理：遗忘 {dropped} 条，合并 {merged} 组，"
            f"人格 {'已更新' if persona else '无变化'}"
        )
        return {"forgotten": dropped, "merged": merged,
                "self_impressions": self_made, "persona": bool(persona)}
