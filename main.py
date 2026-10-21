"""SeekMemory 插件入口。

只做三件事：
1. 把 AstrBot 的事件桥接给 core（不写业务逻辑）
2. 定时触发夜间抽取与每周整理
3. 全程 fail-open —— 记忆系统出任何问题都不能影响正常聊天
"""

from __future__ import annotations

import asyncio
import datetime
import os

from astrbot.api import logger, star
from astrbot.api.event import AstrMessageEvent, filter

from .app.checkpoint import CheckpointManager
from .app.flush_policy import decide_flush
from .core.graph import Graph
from .core.source import Source, make_source_id
from .core.tree import Tree
from .perceive.absorb import absorb, worth_now
from .perceive.buffer import Buffer
from .perceive.calls import log_call
from .perceive.model import ProviderChatModel
from .perceive.compress import build_compress_prompt, parse_compress
from .recall.designated import is_private
from .recall.pipeline import build_block
from .store.cache import Cache
from .store.db import DB


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
        self.checkpoint: CheckpointManager | None = None
        self._flushing = False
        self._flush_day = ""
        self._flush_count = 0
        self._init_engine()

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
            path = str(self._c("db_path", "")) or os.path.join(
                "/AstrBot/data/plugin_data/seekmemory", "memory.db"
            )
            os.makedirs(os.path.dirname(path), exist_ok=True)
            self.db = DB(path)
            self.cache = Cache(self.db)
            self.cache.load()
            self.tree = Tree(self.db, self.cache)
            self.graph = Graph(self.db, self.cache)
            self.ready = True
            self.buffer = Buffer(os.path.join(os.path.dirname(path), "pending.json"))
            self.checkpoint = CheckpointManager(self.db, self.cache,
                                                int(self._c("checkpoint_seconds", 1800)))
            logger.info(
                f"[seekmemory] 已加载 {self.cache.size()} 条记忆，"
                f"待抽取 {len(self.buffer.items)} 条"
            )
        except Exception as e:  # noqa: BLE001
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
            block, info = self._recall_block(text, umo, is_private(event),
                                            str(event.get_sender_id()))
            log_call(self._calls_path(), umo, info)
            if self.checkpoint is not None:
                for art_id in info.get("picked_ids", ()):
                    art = self.cache.get(str(art_id))
                    if art is not None:
                        self.checkpoint.record(art)
            if block:
                req.system_prompt = (req.system_prompt or "") + "\n\n" + block + "\n"
                if self._c("debug_log", False):
                    logger.info(f"[seekmemory] 注入 {len(block)} 字")
        except Exception as e:  # noqa: BLE001
            logger.error(f"[seekmemory] 注入失败（不影响回复）：{e}")

    def _calls_path(self) -> str:
        """调用日志路径：和数据目录放一起。"""
        db = self._c("db_path", "")
        base = os.path.dirname(str(db)) if db else "/AstrBot/data/plugin_data/seekmemory"
        return os.path.join(base, "calls.jsonl")

    def _recall_block(self, text: str, umo: str = "", private: bool = False,
                      speaker: str = "") -> tuple[str, dict]:
        """交给读路径模块：常驻层 + 检索 + 偶然浮现。"""
        return build_block(self.cache, self.graph, self.db, umo, text, private,
                           self._c, self.owner_umo, speaker,
                           log=lambda msg: logger.info(f"[seekmemory] {msg}"))

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
            event_id = str(getattr(getattr(event, "message_obj", None), "message_id", "") or "")
            now = datetime.datetime.now().isoformat(timespec="seconds")
            source_id = make_source_id(event_id=event_id, session_id=umo,
                                       speaker_id=sender, role="user", text=text, at=now)
            turn_id = event_id or source_id
            source = Source(source_id, turn_id, umo, sender, "user", text, now)
            if self.db is not None:
                self.db.append_sources([source])
            self.buffer.add(umo, text, sender, source_id)
            event.set_extra("_seekmemory_turn_id", turn_id)
            event.set_extra("_seekmemory_source_id", source_id)
        except Exception:
            pass

    @filter.on_llm_response()
    async def capture_reply(self, event: AstrMessageEvent, response) -> None:
        try:
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
                turn_id = make_source_id(session_id=umo, speaker_id=str(event.get_sender_id()),
                                          role="assistant", text=text)
            source_id = make_source_id(event_id=f"{turn_id}:assistant", session_id=umo,
                                       speaker_id=str(event.get_self_id()), role="assistant",
                                       text=text)
            now = datetime.datetime.now().isoformat(timespec="seconds")
            source = Source(source_id, turn_id, umo, str(event.get_self_id()),
                            "assistant", text, now,
                            reply_to=str(event.get_extra("_seekmemory_source_id", "") or ""))
            self.db.append_sources([source])
        except Exception:
            pass

    @filter.on_astrbot_loaded()
    async def start_jobs(self) -> None:
        asyncio.create_task(self._nightly_loop())
        asyncio.create_task(self._weekly_loop())
        asyncio.create_task(self._idle_loop())
        asyncio.create_task(self._checkpoint_loop())

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
            await asyncio.sleep(self._seconds_until(str(self._c("summary_time", "23:50"))))
            try:
                await self._nightly()
            except Exception as e:  # noqa: BLE001
                logger.error(f"[seekmemory] 夜间整理失败：{e}")

    async def _weekly_loop(self) -> None:
        while True:
            await asyncio.sleep(self._seconds_until("23:55", weekday=self._c("weekly_day", 6)))
            try:
                await self._weekly()
            except Exception as e:  # noqa: BLE001
                logger.error(f"[seekmemory] 每周整理失败：{e}")

    @staticmethod
    def _seconds_until(hhmm: str, weekday: int | None = None) -> float:
        try:
            hh, mm = (int(x) for x in hhmm.split(":"))
        except Exception:
            hh, mm = 23, 50
        now = datetime.datetime.now()
        target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if target <= now:
            target += datetime.timedelta(days=1)
        if weekday is not None:
            while target.weekday() != weekday:
                target += datetime.timedelta(days=1)
        return max((target - now).total_seconds(), 60)

    # ---------------- 抽取：空闲触发 + 夜间兜底 ----------------
    def _should_flush(self) -> bool:
        if self._flushing or self.buffer is None or self.db is None:
            return False
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
        )
        return decision.should

    async def _idle_loop(self) -> None:
        """聊完安静一会儿就抽，不用等到半夜。"""
        while True:
            await asyncio.sleep(30)
            try:
                if self._should_flush():
                    await self._flush("空闲")
            except Exception as e:  # noqa: BLE001
                logger.error(f"[seekmemory] 空闲抽取失败：{e}")

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
        return ordered[:max(1, cap)]

    async def _flush(self, reason: str) -> None:
        if self._flushing or self.buffer is None or not self.buffer.items or self.db is None:
            return
        self._flushing = True
        try:
            items = list(self.buffer.items)
            sessions = self._split_sessions(items)
            ready = []
            for umo, part in sessions:
                prov = await self.context.get_using_provider_async(umo or None)
                if not prov:
                    logger.warning(f"[seekmemory] no provider for session {umo}")
                    continue
                ready.append((umo, part, prov))
            if not ready:
                return
            self.buffer.take_sessions({umo for umo, _part, _prov in ready})
            self._flush_count += 1
            written = 0
            for umo, part, prov in ready:
                model = ProviderChatModel(prov)
                got = await absorb(
                    part, self.db, self.cache, self.graph, model,
                    log=lambda msg: logger.warning(f"[seekmemory] {msg}"),
                )
                written += got
                logger.info(f"[seekmemory] {reason} extract {umo or 'unknown'}: "
                            f"{len(part)} messages, wrote {got}")
            logger.info(
                f"[seekmemory] {reason} flush: {len(ready)} sessions, "
                f"wrote {written} (daily #{self._flush_count})"
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
        dropped = decay_all(self.db, self.cache, today)
        merged = merge_similar(self.db, self.cache, threshold=0.6)
        persona = distill_persona(self.db, self.cache, today, self.owner_umo)
        logger.info(
            f"[seekmemory] 每周整理：遗忘 {dropped} 条，合并 {merged} 组，"
            f"人格 {'已更新' if persona else '无变化'}"
        )
