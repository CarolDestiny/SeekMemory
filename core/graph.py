"""关系图：similar / causal / temporal 三种边的写入与邻居查询。

边由 store 层持久化；本模块只做 kind 过滤、去重与取最大权重，
不写 SQL，也不缓存图结构（邻居查询直接走 db.edges_of）。
"""

from __future__ import annotations

from typing import Any

KINDS = ("similar", "causal", "temporal")


class Graph:
    """记忆之间的关系图，供激活扩散使用。"""

    def __init__(self, db: Any, cache: Any) -> None:
        self.db = db
        self.cache = cache

    def link(self, src: str, dst: str, kind: str, weight: float) -> None:
        """建立一条 src → dst 的关系边；重复写入同一条边时更新权重。"""
        if kind not in KINDS:
            raise ValueError(f"未知边类型：{kind!r}，可选：{'|'.join(KINDS)}")
        if not src or not dst:
            raise ValueError("边的两端 id 都不能为空")
        if src == dst:
            raise ValueError("不能把节点连到自己")
        self.db.add_edge(src, dst, kind, float(weight))

    def neighbours(
        self,
        node_id: str,
        kinds: tuple[str, ...] = KINDS,
    ) -> list[tuple[str, float]]:
        """返回邻居 (id, weight)，同一邻居取最大权重，按 id 稳定排序。"""
        if not node_id or self.db is None:
            return []
        allowed = set(kinds)
        best: dict[str, float] = {}
        for edge in self.db.edges_of(node_id):
            if len(edge) < 3:
                continue
            other, kind, weight = edge[0], edge[1], edge[2]
            if not other or other == node_id or kind not in allowed:
                continue
            try:
                value = float(weight)
            except (TypeError, ValueError):
                continue
            if other not in best or value > best[other]:
                best[other] = value
        return sorted(best.items())
