"""SeekMemory 插件入口。

只做三件事：
1. 把 AstrBot 的事件桥接给 core（不写业务逻辑）
2. 定时触发夜间抽取与每周整理
3. 全程 fail-open —— 记忆系统出任何问题都不能影响正常聊天
"""

from __future__ import annotations

import asyncio
import datetime
from functools import partial
from pathlib import Path

from astrbot.api import logger, star
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

from .core.graph import Graph
from .core.tree import Tree
from .perceive.absorb import absorb, worth_now
from .perceive.buffer import Buffer
from .perceive.calls import log_call
from .recall.designated import is_private
from .recall.pipeline import build_block
from .store.cache import Cache
from .store.db import DB
from .webui.jobs import Jobs
from .webui.journal import Journal
from .webui.routes import WebRoutes


class Main(star.Star):
    def __init__(self, context: star.Context, config: dict | None = None) -> None:
        super().__init__(context, config)
        self.cfg = config or {}
        self.ready = False
        self.db: DB | None = None
        self.cache: Cache | None = None
        self.tree: Tree | None = None
        self.graph: Graph | None = None
        self.buffer: Buffer | None = None
        self._flushing = False
        self._flush_day = ""
        self._flush_count = 0
        self._schedulers: list[asyncio.Task] = []
        self.data_path = (
            Path(str(self._c("db_path", ""))).expanduser()
            if self._c("db_path", "")
            else Path(get_astrbot_plugin_data_path()) / "seekmemory" / "memory.db"
        )
        self.journal = Journal(self.data_path.parent / "lifecycle.jsonl")
        self.jobs = Jobs(self.journal)
        self._init_engine()
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
            self.buffer = Buffer(str(self.data_path.parent / "pending.json"))
            self.ready = True
            self.journal.record(
                "plugin", "ready", f"Loaded {self.cache.size()} active artifacts"
            )
            logger.info(
                f"[seekmemory] 已加载 {self.cache.size()} 条记忆，"
                f"待抽取 {len(self.buffer.items)} 条"
            )
        except Exception as e:  # noqa: BLE001
            self.journal.record(
                "plugin", "failed", "Engine initialization failed", error=e
            )
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
        if not self.ready or self.cache is None:
            return
        try:
            if not self._may_recall(event):
                return
            text = (event.message_str or "").strip()
            if not text:
                return

            umo = str(getattr(event, "unified_msg_origin", "") or "")
            block, info = self._recall_block(
                text, umo, is_private(event), str(event.get_sender_id())
            )
            log_call(self._calls_path(), umo, info)
            self.journal.record(
                "recall",
                "info",
                "Recall assembled",
                stage="assemble",
                context={key: info[key] for key in ("mode", "picked", "chars")},
            )
            if block:
                req.system_prompt = (req.system_prompt or "") + "\n\n" + block + "\n"
                if self._c("debug_log", False):
                    logger.info(f"[seekmemory] 注入 {len(block)} 字")
        except Exception as e:  # noqa: BLE001
            self.journal.record("recall", "failed", "Recall failed", error=e)
            logger.error(f"[seekmemory] 注入失败（不影响回复）：{e}")

    def _calls_path(self) -> str:
        """调用日志路径：和数据目录放一起。"""
        return str(self.data_path.parent / "calls.jsonl")

    def _recall_block(
        self, text: str, umo: str = "", private: bool = False, speaker: str = ""
    ) -> tuple[str, dict]:
        """交给读路径模块：常驻层 + 检索 + 偶然浮现。"""
        return build_block(
            self.cache,
            self.graph,
            self.db,
            umo,
            text,
            private,
            self._c,
            self.owner_umo,
            speaker,
            log=lambda msg: logger.info(f"[seekmemory] {msg}"),
        )

    # ---------------- 写路径：缓冲 ----------------
    @filter.event_message_type(filter.EventMessageType.ALL)
    async def buffer_message(self, event: AstrMessageEvent) -> None:
        try:
            if not self._may_observe(event):
                return
            text = (event.message_str or "").strip()
            if text and self.buffer is not None:
                umo = str(getattr(event, "unified_msg_origin", "") or "")
                self.buffer.add(umo, text, str(event.get_sender_id()))
        except Exception:  # noqa: BLE001
            pass

    # ---------------- 定时 ----------------
    @filter.on_astrbot_loaded()
    async def start_jobs(self) -> None:
        if not self.ready or self.jobs.closed or self._schedulers:
            return
        self._schedulers = [
            asyncio.create_task(operation())
            for operation in (self._nightly_loop, self._weekly_loop, self._idle_loop)
        ]
        self.journal.record("scheduler", "running", "Maintenance schedules started")

    async def initialize(self) -> None:
        """Start schedules on activation, including plugin reload."""
        await self.start_jobs()

    async def terminate(self) -> None:
        """Cancel owned tasks, detach routes, and close storage in that order."""
        self.ready = False
        for task in self._schedulers:
            task.cancel()
        await asyncio.gather(*self._schedulers, return_exceptions=True)
        self._schedulers.clear()
        await self.jobs.close()
        self.web.close()
        if self.buffer is not None:
            self.buffer.save()
        if self.db is not None:
            self.db.close()
            self.db = None
        self.journal.record("plugin", "stopped", "Plugin resources released")

    async def _nightly_loop(self) -> None:
        while True:
            await asyncio.sleep(
                self._seconds_until(str(self._c("summary_time", "23:50")))
            )
            try:
                self.jobs.submit("nightly", self._nightly)
            except Exception as e:  # noqa: BLE001
                logger.error(f"[seekmemory] 夜间整理失败：{e}")
                self.journal.record(
                    "scheduler", "failed", "Schedule submission failed", error=e
                )

    async def _weekly_loop(self) -> None:
        while True:
            await asyncio.sleep(
                self._seconds_until("23:55", weekday=self._c("weekly_day", 6))
            )
            try:
                self.jobs.submit("weekly", self._weekly)
            except Exception as e:  # noqa: BLE001
                logger.error(f"[seekmemory] 每周整理失败：{e}")
                self.journal.record(
                    "scheduler", "failed", "Schedule submission failed", error=e
                )

    @staticmethod
    def _seconds_until(hhmm: str, weekday: int | None = None) -> float:
        try:
            hh, mm = (int(x) for x in hhmm.split(":"))
            if not 0 <= hh <= 23 or not 0 <= mm <= 59:
                raise ValueError("Invalid schedule")
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
    def _should_flush(self) -> bool:
        """白天要不要抽：安静够久 + 攒够条数 + 有值得记的事 + 没超每天上限。"""
        if self._flushing or self.buffer is None or self.db is None:
            return False
        idle = float(self._c("idle_flush_seconds", 0))
        if idle <= 0:  # 0 = 白天不抽，只等晚上批量
            return False
        if not self.buffer.should_flush(idle, int(self._c("min_pending", 8))):
            return False
        if not worth_now(self.buffer.items):
            return False
        today = datetime.date.today().isoformat()
        if self._flush_day != today:
            self._flush_day, self._flush_count = today, 0
        return self._flush_count < int(self._c("max_flushes_per_day", 2))

    async def _idle_loop(self) -> None:
        """聊完安静一会儿就抽，不用等到半夜。"""
        while True:
            await asyncio.sleep(30)
            try:
                if self._should_flush():
                    self.jobs.submit("idle", lambda: self._flush("idle"))
            except Exception as e:  # noqa: BLE001
                logger.error(f"[seekmemory] 空闲抽取失败：{e}")
                self.journal.record(
                    "scheduler", "failed", "Schedule submission failed", error=e
                )

    async def _nightly(self) -> None:
        """夜间兜底：把白天没来得及抽的尾巴抽掉。"""
        await self._flush("夜间")

    def _split_sessions(self, items: list) -> list[tuple[str, list]]:
        """按会话切开，每个会话单独抽一次；单个夜晚最多处理 N 个会话。"""
        buckets: dict[str, list] = {}
        for row in items:
            buckets.setdefault(str(row[0] or ""), []).append(row)
        cap = int(self._c("max_sessions_per_flush", 6))
        ordered = sorted(buckets.items(), key=lambda kv: len(kv[1]), reverse=True)
        return ordered[: max(1, cap)]

    async def _flush(self, reason: str) -> None:
        """抽一批：调用模型、解析、写库建边；全程 fail-open。"""
        if (
            self._flushing
            or self.buffer is None
            or not self.buffer.items
            or self.db is None
        ):
            return
        self._flushing = True
        try:
            with self.journal.span("extract", "provider.resolve"):
                prov = await self.context.get_using_provider_async()
                if not prov:
                    raise RuntimeError("No model provider is configured")
            items = list(self.buffer.items)
            sessions = self._split_sessions(items)
            self._flush_count += 1
            written = 0
            for umo, part in sessions:
                with self.journal.span(
                    "extract", "session.extract", session=umo, messages=len(part)
                ) as metrics:
                    got = await absorb(
                        part,
                        self.db,
                        self.cache,
                        self.graph,
                        prov,
                        log=partial(self.journal.record, "extract", "warning"),
                        strict=True,
                        stage=partial(self.journal.span, "extract"),
                    )
                    metrics["written"] = got
                # Keep in-flight messages persisted until processing succeeds.
                # Identity preserves identical messages arriving during the await.
                processed = {id(row) for row in part}
                self.buffer.items = [
                    row for row in self.buffer.items if id(row) not in processed
                ]
                self.buffer.save()
                written += got
                logger.info(
                    f"[seekmemory] {reason}抽取 {umo or '未知会话'}："
                    f"{len(part)} 条对话，写入 {got} 条"
                )
            logger.info(
                f"[seekmemory] {reason}抽取：{len(sessions)} 个会话，"
                f"共写入 {written} 条（今日第 {self._flush_count} 次）"
            )
            self.journal.record(
                "extract",
                "info",
                f"sessions={len(sessions)} written={written}",
                context={"sessions": len(sessions), "written": written},
                stage="batch.complete",
            )
        finally:
            self._flushing = False

    async def _weekly(self) -> None:
        from .maintain.decay import decay_all
        from .maintain.merge import merge_similar
        from .maintain.persona import distill_persona

        if self.db is None or self.cache is None:
            return
        today = datetime.date.today().isoformat()
        with self.journal.span("weekly", "decay") as metrics:
            dropped = decay_all(self.db, self.cache, today)
            metrics["forgotten"] = dropped
        with self.journal.span("weekly", "merge", threshold=0.6) as metrics:
            merged = merge_similar(self.db, self.cache, threshold=0.6)
            metrics["merged"] = merged
        with self.journal.span("weekly", "persona") as metrics:
            persona = distill_persona(self.db, self.cache, today, self.owner_umo)
            metrics["updated"] = bool(persona)
        self.journal.record(
            "weekly",
            "info",
            f"forgotten={dropped} merged={merged} persona={bool(persona)}",
            self.jobs.task_id,
        )
        logger.info(
            f"[seekmemory] 每周整理：遗忘 {dropped} 条，合并 {merged} 组，"
            f"人格 {'已更新' if persona else '无变化'}"
        )
