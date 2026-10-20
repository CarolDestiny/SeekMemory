"""recall.spread：从种子出发沿关系边做激活扩散。"""

from __future__ import annotations

from core.graph import Graph
from store.cache import Cache

DECAY = 0.5
MAX_PER_ROUND = 20
MAX_ACTIVATION = 1.0


def _neighbours(graph: Graph, node_id: str) -> list[tuple[str, float]]:
    """读取邻居，图损坏时返回空列表（fail-open）。"""
    try:
        return list(graph.neighbours(node_id))
    except Exception:
        return []


def _alive(cache: Cache, node_id: str) -> bool:
    """缓存明确标记非 active 才跳过；未命中或异常时放行（fail-open）。"""
    try:
        art = cache.get(node_id)
    except Exception:
        return True
    if art is None:
        return True
    return getattr(getattr(art, "header", None), "state", "active") == "active"


def _weight(value: float) -> float:
    """把边权夹到 0~1，非法值按 0 处理。"""
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def activate(
    seed_ids: list[str],
    graph: Graph,
    cache: Cache,
    rounds: int = 2,
) -> dict[str, float]:
    """
    从种子出发沿 edges 扩散，返回 {node_id: 激活值}。

    种子激活 1.0；每跳乘 0.5 与边权，同一节点取最大路径；
    每轮只保留新激活的 top 20，避免大图指数膨胀。
    """
    scores: dict[str, float] = {sid: MAX_ACTIVATION for sid in seed_ids if sid}
    frontier = dict(scores)
    for _ in range(max(0, rounds)):
        candidates: dict[str, float] = {}
        for node_id, value in frontier.items():
            for nid, weight in _neighbours(graph, node_id):
                if not nid or not _alive(cache, nid):
                    continue
                contribution = value * DECAY * _weight(weight)
                best = max(scores.get(nid, 0.0), candidates.get(nid, 0.0))
                if contribution <= best:
                    continue
                candidates[nid] = min(MAX_ACTIVATION, contribution)
        if not candidates:
            break
        ranked = sorted(candidates.items(), key=lambda item: (-item[1], item[0]))
        frontier = dict(ranked[:MAX_PER_ROUND])
        for nid, value in frontier.items():
            scores[nid] = max(scores.get(nid, 0.0), value)
    return scores
