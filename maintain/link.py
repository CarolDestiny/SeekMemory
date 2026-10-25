"""写入时建联想边：相似边按二元组重合度，时序边按同一天写入。

causal 边需要语义判断，暂不自动建；显式接口留在 ``core.graph.Graph.link_causal``。
本模块是写入路径的便利层：``persist`` 先写库再建边，建边失败只损失边，
不影响已经完成的写入（fail-open）。
"""

from __future__ import annotations

import re
from typing import Any

try:  # 作为 astrbot 插件包的一部分导入
    from ..core.artifact import Artifact, content_of, revise
    from ..core.graph import Graph
    from ..store.cache import Cache
    from ..store import Store, open_store
except ImportError:  # 作为顶层包导入（脚本 / 测试）
    from core.artifact import Artifact, content_of, revise
    from core.graph import Graph
    from store.cache import Cache
    from store import Store, open_store

SIMILAR_BAR = 0.45
MAX_SIMILAR = 3
MAX_TEMPORAL = 2
TEMPORAL_WEIGHT = 0.3
MAX_EDGES = 5

_PUNCT = re.compile(r"[^\w\u4e00-\u9fff]+")


def _text(art: Artifact) -> str:
    """取可读文本；坏节点回退 payload["text"]，再不行返回空串。"""
    try:
        text = content_of(art)
    except Exception:  # noqa: BLE001 - 单条坏记忆不能中断建边
        text = ""
    return str(text or art.payload.get("text") or "")


def _bigrams(text: str) -> set[str]:
    """规范化字符二元组：去标点、转小写，中文不再分词。"""
    plain = _PUNCT.sub("", str(text or "")).lower()
    if len(plain) < 2:
        return {plain} if plain else set()
    return {plain[index : index + 2] for index in range(len(plain) - 1)}


def _overlap(left: str, right: str) -> float:
    """二元组 Dice 重合度，0 表示无关、1 表示完全重合。"""
    a, b = _bigrams(left), _bigrams(right)
    if not a or not b:
        return 0.0
    return 2.0 * len(a & b) / (len(a) + len(b))


def _day(value: Any) -> str:
    """取 ISO 时间的日期部分（前 10 位）；空值或短串返回空串。"""
    text = str(value or "")
    return text[:10] if len(text) >= 10 else ""


def _edges(db: Store, node_id: str) -> list[tuple[str, str, float]]:
    """读取节点的全部边；存储异常时按无边处理，保证 fail-open。"""
    try:
        return list(db.artifacts.edges_of(node_id))
    except Exception:  # noqa: BLE001
        return []


def _has_edge(db: Store, src: str, dst: str, kind: str | None = None) -> bool:
    """判断 src 与 dst 之间是否已有边；kind 为 None 时任意类型都算。"""
    for edge in _edges(db, src):
        if len(edge) < 3 or edge[0] != dst:
            continue
        if kind is None or edge[1] == kind:
            return True
    return False


def _candidate_pool(art: Artifact, cache: Cache) -> list[Artifact]:
    """同 scope 的 active memory；不跨 scope 连边，避免私聊关系进群聊。"""
    scope = str(art.header.scope or "private")
    return [
        other
        for other in cache.active("memory")
        if other.header.id != art.header.id
        and other.header.state == "active"
        and str(other.header.scope or "private") == scope
    ]


def _link(art: Artifact, graph: Graph, cache: Cache,
          created: str | None = None) -> int:
    """在出度预算内建 similar / temporal 边，返回实际新增的边数。"""
    db = getattr(graph, "db", None)
    if db is None:
        return 0
    pool = _candidate_pool(art, cache)
    room = MAX_EDGES - len(_edges(db, art.header.id))
    if room <= 0 or not pool:
        return 0

    text = _text(art)
    similar = [
        (_overlap(text, _text(other)), other)
        for other in pool
    ]
    similar = sorted(
        ((score, other) for score, other in similar if score > SIMILAR_BAR),
        key=lambda item: (-item[0], item[1].header.id),
    )

    added = 0
    for score, other in similar[:MAX_SIMILAR]:
        if added >= room:
            break
        other_id = other.header.id
        if len(_edges(db, other_id)) >= MAX_EDGES:
            continue
        if _has_edge(db, art.header.id, other_id):
            continue
        try:
            graph.link(art.header.id, other_id, "similar", score)
        except Exception:  # noqa: BLE001 - 单条边失败不能拖垮其余边
            continue
        added += 1

    day = _day(created or art.header.time.created)
    if not day or added >= room:
        return added
    same_day = [
        other
        for other in pool
        if _day(other.header.time.created) == day
        and not _has_edge(db, art.header.id, other.header.id)
    ]
    same_day.sort(key=lambda other: (other.header.time.created, other.header.id),
                  reverse=True)
    temporal = 0
    for other in same_day:
        if added >= room or temporal >= MAX_TEMPORAL:
            break
        other_id = other.header.id
        if len(_edges(db, other_id)) >= MAX_EDGES:
            continue
        try:
            graph.link(art.header.id, other_id, "temporal", TEMPORAL_WEIGHT)
        except Exception:  # noqa: BLE001
            continue
        added += 1
        temporal += 1
    return added


def link_new(art: Artifact, graph: Graph | None, cache: Cache | None,
             created: str | None = None) -> int:
    """为新写入的记忆建边；任何失败都返回 0，调用方可以安全忽略。"""
    if graph is None or cache is None:
        return 0
    try:
        return _link(art, graph, cache, created)
    except Exception:  # noqa: BLE001 - 建边是增强，失败不能影响写入
        return 0


def persist(art: Artifact, db: Store, cache: Cache | None, graph: Graph | None) -> int:
    # Compatibility writer: route every write through the CAS commit path.
    existing = db.artifacts.get(art.header.id)
    if existing is None:
        op = "create"
        expected = 0
    else:
        op = "revise"
        expected = existing.header.revision
        if art.header.revision <= existing.header.revision:
            art = revise(
                existing,
                payload=art.payload,
                state=art.header.state,
                scope=art.header.scope,
                strength=art.header.strength,
                lineage=art.header.lineage,
                said_by=art.header.said_by,
                shareable=art.header.shareable,
                subject_id=art.header.subject_id,
            )
    db.artifacts.commit(art, expected_revision=expected, op=op, reason="persist",
              source_ids=tuple(art.header.lineage.sources))
    if cache is not None:
        cache.put(art)
    return link_new(art, graph, cache)
