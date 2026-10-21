"""把缓冲里的对话抽成记忆并落库。

一步做完：拼对话 → 调模型 → 解析 JSON → 去重 → 构造 artifact → 校验 → 写库建边。
任何一步失败都只丢这一批，不影响聊天。
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

try:  # 作为 astrbot 插件包的一部分导入
    from ..core.artifact import Strength, content_of, make, validate
    from ..core.graph import Graph
    from ..maintain.link import persist
    from ..perceive.extract import (
        build_prompt,
        filter_duplicates,
        parse_response,
    )
    from ..store.cache import Cache
    from ..store.db import DB
except ImportError:  # 作为顶层包导入（脚本 / 测试）
    from core.artifact import Strength, content_of, make, validate
    from core.graph import Graph
    from maintain.link import persist
    from perceive.extract import build_prompt, filter_duplicates, parse_response
    from store.cache import Cache
    from store.db import DB

MAX_ITEMS = 6
Log = Callable[[str], None]


def _num(value: Any, default: float, low: float, high: float) -> float:
    """把模型给的数值收进区间；缺失、NaN 或非法值回落到默认值。"""
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    if number != number:  # NaN
        return default
    return max(low, min(high, number))


def strength_of(item: dict) -> dict:
    """从抽取结果取情绪与命中字段，缺省回落到 Strength 的默认值。"""
    base = Strength()
    out = {
        "arousal": _num(item.get("arousal"), base.arousal, 0.0, 1.0),
        "valence": _num(item.get("valence"), base.valence, -1.0, 1.0),
        "funny": _num(item.get("funny"), base.funny, 0.0, 1.0),
    }
    hits = item.get("hits")
    if hits is not None:
        try:
            out["hits"] = max(0, int(hits))
        except (TypeError, ValueError):
            pass
    return out


def dialogue_of(items: list[tuple[str, str, str]]) -> str:
    """把 (umo, role, text) 拼成给模型看的对话文本。"""
    return "\n".join(f"{role}: {text}" for _umo, role, text in items[-120:])


def existing_texts(cache: Cache | None) -> list[str]:
    """已有记忆正文，供抽取去重。"""
    if cache is None:
        return []
    try:
        return [content_of(a) for a in cache.active("memory")]
    except Exception:  # noqa: BLE001 - 读不到就当作没有
        return []


def owner_of(items: list[tuple[str, str, str]]) -> str:
    """只有整批来自同一个会话时才记归属，混会话就不写归属。"""
    umos = {u for u, _r, _t in items if u}
    return next(iter(umos)) if len(umos) == 1 else ""


async def absorb(
    items: list[tuple[str, str, str]],
    db: DB,
    cache: Cache | None,
    graph: Graph | None,
    provider: Any,
    log: Log = lambda _msg: None,
) -> int:
    """抽取并写入，返回写入条数；模型或解析失败返回 0。"""
    if not items or db is None or provider is None:
        return 0
    try:
        resp = await provider.text_chat(
            system_prompt=build_prompt([]), prompt=dialogue_of(items)
        )
        raw = getattr(resp, "completion_text", "") or ""
    except Exception as exc:  # noqa: BLE001 - 抽取失败不抛给上层
        log(f"抽取调用失败：{exc}")
        return 0

    parsed = parse_response(raw)
    parsed = filter_duplicates(parsed, existing_texts(cache))
    if not parsed:
        return 0

    owner = owner_of(items)
    written = 0
    for item in parsed[:MAX_ITEMS]:
        try:
            if owner:
                item = {**item, "owner_umo": owner}
            art = make("memory", item, strength=strength_of(item))
            validate(art)
        except Exception as exc:  # noqa: BLE001 - 单条坏数据跳过
            log(f"构造记忆失败：{exc}")
            continue
        try:
            persist(art, db, cache, graph)
            written += 1
        except Exception as exc:  # noqa: BLE001
            log(f"写入失败：{exc}")
    return written
