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
import os

from astrbot.api import logger, star
from astrbot.api.event import AstrMessageEvent, filter

from .core.artifact import Strength, make, validate
from .core.graph import Graph
from .core.tree import Tree
from .perceive.compress import build_compress_prompt, parse_compress
from .perceive.extract import (
    build_prompt,
    filter_duplicates,
    parse_response,
)
from .recall.assemble import build as assemble_text
from .recall.score import select
from .recall.seed import seeds
from .recall.spread import activate
from .store.cache import Cache
from .store.db import DB


def _clamp(value: object, default: float, low: float, high: float) -> float:
    """把模型给的数值收敛到区间；缺失、NaN 或非法值回落到默认值。"""
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    if number != number:  # NaN
        return default
    return max(low, min(high, number))


def _strength_of(item: dict) -> dict:
    """从抽取结果取情绪与命中字段，缺省回落到 Strength 的默认值。"""
    base = Strength()
    strength = {
        "arousal": _clamp(item.get("arousal"), base.arousal, 0.0, 1.0),
        "valence": _clamp(item.get("valence"), base.valence, -1.0, 1.0),
        "funny": _clamp(item.get("funny"), base.funny, 0.0, 1.0),
    }
    hits = item.get("hits")
    if hits is not None:
        try:
            strength["hits"] = max(0, int(hits))
        except (TypeError, ValueError):
            pass
    return strength


class Main(star.Star):
    def __init__(self, context: star.Context, config: dict | None = None) -> None:
        super().__init__(context, config)
        self.cfg = config or {}
        self.ready = False
        self.db: DB | None = None
        self.cache: Cache | None = None
        self.tree: Tree | None = None
        self.graph: Graph | None = None
        self._pending: list[tuple[str, str]] = []  # (role, text) 当天缓冲
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
            logger.info(f"[seekmemory] 已加载 {self.cache.size()} 条记忆")
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

            block = self._recall_block(text)
            if block:
                req.system_prompt = (req.system_prompt or "") + "\n\n" + block + "\n"
                if self._c("debug_log", False):
                    logger.info(f"[seekmemory] 注入 {len(block)} 字")
        except Exception as e:  # noqa: BLE001
            logger.error(f"[seekmemory] 注入失败（不影响回复）：{e}")

    def _recall_block(self, text: str) -> str:
        assert self.cache is not None and self.graph is not None
        pool = self.cache.active()
        if not pool:
            return ""

        seed_ids = seeds(text, pool)
        activation = activate(seed_ids, self.graph, self.cache)
        candidates = [(a, float(activation.get(a.header.id, 0.0))) for a in pool]
        picked = select(
            candidates,
            text,
            0.0,
            k=self._c("recall_k", 8),
            explore=self._c("explore_rate", 0.1),
        )
        return assemble_text(picked, budget=self._c("budget_chars", 600))

    # ---------------- 写路径：缓冲 ----------------
    @filter.event_message_type(filter.EventMessageType.ALL)
    async def buffer_message(self, event: AstrMessageEvent) -> None:
        try:
            if not self._may_remember(event):
                return
            text = (event.message_str or "").strip()
            if text:
                self._pending.append(("user", text))
                self._pending = self._pending[-200:]
        except Exception:  # noqa: BLE001
            pass

    # ---------------- 定时 ----------------
    @filter.on_astrbot_loaded()
    async def start_jobs(self) -> None:
        asyncio.create_task(self._nightly_loop())
        asyncio.create_task(self._weekly_loop())

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

    async def _nightly(self) -> None:
        if not self._pending or self.db is None:
            return
        prov = await self.context.get_using_provider_async()
        if not prov:
            return

        dialogue = "\n".join(f"{r}: {t}" for r, t in self._pending[-120:])
        resp = await prov.text_chat(
            system_prompt=build_prompt([]), prompt=dialogue
        )
        items = parse_response(getattr(resp, "completion_text", "") or "")
        items = filter_duplicates(items, [a for a in self._existing_texts()])
        if not items:
            self._pending = []
            return

        written = 0
        for it in items[:3]:
            try:
                art = make("memory", it, strength=_strength_of(it))
                validate(art)
            except ValueError as e:
                logger.warning(f"[seekmemory] 抽取结果校验失败，已跳过：{e}")
                continue
            except Exception as e:  # noqa: BLE001
                logger.error(f"[seekmemory] 构造记忆失败，已跳过：{e}")
                continue
            try:
                self.db.upsert(art)
                if self.cache:
                    self.cache.put(art)
                written += 1
            except Exception as e:  # noqa: BLE001
                logger.error(f"[seekmemory] 写入失败：{e}")
        self._pending = []
        logger.info(f"[seekmemory] 夜间写入 {written} 条")

    def _existing_texts(self) -> list[str]:
        if not self.cache:
            return []
        from .core.artifact import content_of

        return [content_of(a) for a in self.cache.active("memory")]

    async def _weekly(self) -> None:
        from .maintain.decay import decay_all
        from .maintain.merge import merge_similar

        if self.db is None or self.cache is None:
            return
        today = datetime.date.today().isoformat()
        dropped = decay_all(self.db, self.cache, today)
        merged = merge_similar(self.db, self.cache, threshold=0.6)
        logger.info(f"[seekmemory] 每周整理：遗忘 {dropped} 条，合并 {merged} 组")
