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

from .core.graph import Graph
from .core.tree import Tree
from .perceive.absorb import absorb
from .perceive.buffer import Buffer
from .perceive.compress import build_compress_prompt, parse_compress
from .recall.assemble import build as assemble_text
from .recall.designated import deliverable, is_private, mark_given
from .recall.drift import best_of as drift_best, should_drift
from .recall.intent import intent_of
from .recall.gate import pinned
from .recall.scope import visible
from .recall.score import select
from .recall.seed import seeds
from .recall.spread import activate
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
        self._flushing = False
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
            logger.info(
                f"[seekmemory] 已加载 {self.cache.size()} 条记忆，"
                f"待抽取 {len(self.buffer.items)} 条"
            )
        except Exception as e:  # noqa: BLE001
            logger.error(f"[seekmemory] 初始化失败，记忆功能降级：{e}")

    # ---------------- 权限 ----------------
    def _may_remember(self, event: AstrMessageEvent) -> bool:
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

    # ---------------- 读路径：注入 ----------------
    @filter.on_llm_request()
    async def inject_memory(self, event: AstrMessageEvent, req) -> None:
        if not self.ready or self.cache is None:
            return
        try:
            if not self._may_remember(event):
                return
            text = (event.message_str or "").strip()
            if not text:
                return

            umo = str(getattr(event, "unified_msg_origin", "") or "")
            block = self._recall_block(text, umo, is_private(event))
            if block:
                req.system_prompt = (req.system_prompt or "") + "\n\n" + block + "\n"
                if self._c("debug_log", False):
                    logger.info(f"[seekmemory] 注入 {len(block)} 字")
        except Exception as e:  # noqa: BLE001
            logger.error(f"[seekmemory] 注入失败（不影响回复）：{e}")

    def _visible(self, pool: list, umo: str) -> list:
        """按 scope 过滤候选池：private 只给归属会话，shared/shadow 全放。"""
        lookup = self.db.source_umo if self.db is not None else None
        return visible(pool, umo, self.owner_umo, lookup)

    def _recall_block(self, text: str, umo: str = "", private: bool = False) -> str:
        assert self.cache is not None and self.graph is not None
        # 常驻层（persona + 印象前 2）是固定画像，不经过检索证据闸门。
        pinned_arts = self._visible(pinned(self.cache), umo)
        pool = [a for a in self._visible(self.cache.active(), umo) if deliverable(a, text, private)]
        if not pool and not pinned_arts:
            return ""

        designated = [a for a in pool if a.header.family == "designated"]
        pool = [a for a in pool if a.header.family != "designated"]

        # 这一句值不值得翻记忆：寒暄、问时间、让你写代码都不翻。
        mode = intent_of(text)
        picked: list = []
        if mode != "none" and pool:
            seed_ids = seeds(text, pool)
            activation = activate(seed_ids, self.graph, self.cache)
            candidates = [(a, float(activation.get(a.header.id, 0.0))) for a in pool]
            loose = mode == "loose"
            picked = select(
                candidates,
                text,
                0.0,
                k=self._c("recall_k", 8) + (2 if loose else 0),
                explore=self._c("explore_rate", 0.1),
                gate=True,
                min_ev_abs=self._c("recall_min_ev_abs", 0.5),
                min_ev_rel=0.2 if loose else self._c("recall_min_ev_rel", 0.3),
            )

        # 没有线索的时候，也可能突然想起一件事——这不是检索，是浮现。
        if not picked and should_drift(text, seed=text):
            one = drift_best(pool, seed=text)
            if one is not None:
                picked = [one]
                if self._c("debug_log", False):
                    logger.info(f"[seekmemory] 主动想起：{one.header.id}")

        budget = self._c("budget_chars", 600)
        block = assemble_text(
            pinned_arts + designated + picked,
            budget=int(budget * (1.4 if mode == "loose" else 1.0)),
            text=text,
            is_private=private,
        )
        mark_given(self.db, self.cache, designated + picked, block)
        return block

    # ---------------- 写路径：缓冲 ----------------
    @filter.event_message_type(filter.EventMessageType.ALL)
    async def buffer_message(self, event: AstrMessageEvent) -> None:
        try:
            if not self._may_remember(event):
                return
            text = (event.message_str or "").strip()
            if text and self.buffer is not None:
                umo = str(getattr(event, "unified_msg_origin", "") or "")
                self.buffer.add(umo, text)
        except Exception:  # noqa: BLE001
            pass

    # ---------------- 定时 ----------------
    @filter.on_astrbot_loaded()
    async def start_jobs(self) -> None:
        asyncio.create_task(self._nightly_loop())
        asyncio.create_task(self._weekly_loop())
        asyncio.create_task(self._idle_loop())

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
        """攒够条数、且安静够久，就值得抽一次。"""
        if self._flushing or self.buffer is None or self.db is None:
            return False
        return self.buffer.should_flush(
            float(self._c("idle_flush_seconds", 180)),
            int(self._c("min_pending", 4)),
        )

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

    async def _flush(self, reason: str) -> None:
        """抽一批：调用模型、解析、写库建边；全程 fail-open。"""
        if self._flushing or self.buffer is None or not self.buffer.items or self.db is None:
            return
        self._flushing = True
        try:
            prov = await self.context.get_using_provider_async()
            if not prov:
                return
            items = self.buffer.take()
            written = await absorb(
                items, self.db, self.cache, self.graph, prov,
                log=lambda msg: logger.warning(f"[seekmemory] {msg}"),
            )
            logger.info(f"[seekmemory] {reason}抽取：{len(items)} 条对话，写入 {written} 条")
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
        persona = distill_persona(self.db, self.cache, today)
        logger.info(
            f"[seekmemory] 每周整理：遗忘 {dropped} 条，合并 {merged} 组，"
            f"人格 {'已更新' if persona else '无变化'}"
        )
