"""读路径：一条消息进来，该不该翻记忆、翻哪几条、怎么拼成一段话。

原来嵌在插件入口里，抽出来是为了让 main.py 只做事件桥接。
全部 fail-open：任何异常都由调用方兜住，返回空串也不影响回复。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

try:  # 作为 astrbot 插件包的一部分导入
    from ..core.graph import Graph
    from ..recall.assemble import build as assemble_text
    from ..recall.designated import deliverable, mark_given
    from ..recall.drift import best_of as drift_best
    from ..recall.drift import should_drift
    from ..recall.gate import pinned
    from ..recall.history import trajectory
    from ..recall.intent import intent_of
    from ..recall.scope import visible
    from ..recall.score import select
    from ..recall.seed import seeds
    from ..recall.spread import activate
    from ..store.cache import Cache
    from ..store.db import DB
except ImportError:  # 作为顶层包导入（脚本 / 测试）
    from core.graph import Graph
    from store.cache import Cache
    from store.db import DB

    from recall.assemble import build as assemble_text
    from recall.designated import deliverable, mark_given
    from recall.drift import best_of as drift_best
    from recall.drift import should_drift
    from recall.gate import pinned
    from recall.history import trajectory
    from recall.intent import intent_of
    from recall.scope import visible
    from recall.score import select
    from recall.seed import seeds
    from recall.spread import activate

Conf = Callable[[str, Any], Any]


def subject_of(speaker: str, owner_umo: str) -> str:
    """这条消息的说话人是谁：主人还是某个 QQ。印象按这个人来调。"""
    owner_id = str(owner_umo or "").split(":")[-1] if owner_umo else ""
    talker = str(speaker or "")
    if not talker:
        return "owner"
    return "owner" if owner_id and talker == owner_id else talker


def build_block(
    cache: Cache,
    graph: Graph,
    db: DB,
    umo: str,
    text: str,
    private: bool,
    conf: Conf,
    owner_umo: str,
    speaker: str = "",
    log: Callable[[str], None] = lambda _msg: None,
    *,
    dry_run: bool = False,
) -> tuple[str, dict]:
    """按常驻层、检索和偶然浮现组装会话的记忆注入文本。

    Args:
        cache: 运行中的活跃 Artifact 缓存。
        graph: 用于激活扩散的关系图。
        db: 用于归属查询和指定交付的数据库。
        umo: 完整会话标识。
        text: 触发召回的输入消息。
        private: 是否为私聊。
        conf: 与插件共用的带类型配置查询函数。
        owner_umo: 配置中的所有者会话。
        speaker: 实际发送者身份。
        log: 召回摘要回调。
        dry_run: 管理预览时跳过交付状态写入。

    Returns:
        注入文本与运行决策计数。
    """
    lookup = db.source_umo if db is not None else None
    subject = subject_of(speaker, owner_umo)
    pinned_arts = visible(pinned(cache, subject), umo, owner_umo, lookup)
    pool = [
        a
        for a in visible(cache.active(), umo, owner_umo, lookup)
        if deliverable(a, text, private)
    ]
    if not pool and not pinned_arts:
        return "", {"mode": "none", "picked": 0, "pinned": 0, "chars": 0}

    designated = [a for a in pool if a.header.family == "designated"]
    pool = [a for a in pool if a.header.family != "designated"]

    mode = intent_of(text)
    picked: list = []
    if mode != "none" and pool:
        seed_ids = seeds(text, pool)
        activation = activate(seed_ids, graph, cache)
        candidates = [(a, float(activation.get(a.header.id, 0.0))) for a in pool]
        loose = mode == "loose"
        picked = select(
            candidates,
            text,
            0.0,
            k=int(conf("recall_k", 8)) + (2 if loose else 0),
            explore=float(conf("explore_rate", 0.1)),
            gate=True,
            min_ev_abs=float(conf("recall_min_ev_abs", 0.5)),
            min_ev_rel=0.2 if loose else float(conf("recall_min_ev_rel", 0.3)),
        )

    # 没有线索时也可能突然想起一件事——这不走 query 打分。
    if not picked and should_drift(text, seed=text):
        one = drift_best(pool, seed=text)
        if one is not None:
            picked = [one]
            log(f"主动想起：{one.header.id}")

    budget = int(conf("budget_chars", 600))
    notes = {}
    for art in pinned_arts + picked:
        try:
            if str(art.payload.get("level") or "") == "impression":
                note = trajectory(cache, art)
                if note:
                    notes[art.header.id] = note
        except Exception:  # noqa: BLE001 - 轨迹算不出来就只给当前印象
            continue
    block = assemble_text(
        pinned_arts + designated + picked,
        budget=int(budget * (1.4 if mode == "loose" else 1.0)),
        text=text,
        is_private=private,
        notes=notes,
    )
    if not dry_run:
        mark_given(db, cache, designated + picked, block)
    info = {
        "mode": mode,
        "picked": len(picked),
        "pinned": len(pinned_arts),
        "chars": len(block),
        "drift": bool(picked) and not designated,
    }
    return block, info
