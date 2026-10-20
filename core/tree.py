"""抽象树：impression / scene / detail 三级的父子关系与查询。

节点内容由 DB/Cache 持有；Tree 负责两件事：
1. 用 db.set_parent（若存在）记录父指针，供持久化层按 parent 列查询；
2. 用 kind="tree_child:<父 id>" 的边记录父子关系，使 children() 在
   db.edges_of 双向返回时仍能分辨方向（只认后缀等于本节点的那条边）。
本模块不写 SQL。
"""

from __future__ import annotations

from typing import Any

from .artifact import Artifact

EDGE_PREFIX = "tree_child:"
LEVELS = ("impression", "scene", "detail")


class Tree:
    """维护记忆的抽象层级，存储通过注入的 db/cache 完成。"""

    def __init__(self, db: Any, cache: Any) -> None:
        self.db = db
        self.cache = cache

    def _get(self, node_id: str) -> Artifact | None:
        art = self.cache.get(node_id) if self.cache is not None else None
        if art is not None:
            return art
        return self.db.get(node_id) if self.db is not None else None

    def _persist(self, art: Artifact) -> None:
        self.db.upsert(art)
        if self.cache is not None:
            self.cache.put(art)

    def children(self, node_id: str) -> list[Artifact]:
        """返回 node_id 的直接子节点；边或节点缺失时跳过。"""
        if not node_id or self.db is None:
            return []
        wanted = EDGE_PREFIX + node_id
        result: list[Artifact] = []
        seen: set[str] = set()
        for edge in self.db.edges_of(node_id):
            if len(edge) < 3:
                continue
            other, kind = edge[0], edge[1]
            if kind != wanted or not other or other in seen:
                continue
            art = self._get(other)
            if art is not None:
                seen.add(other)
                result.append(art)
        return result

    def impressions(self) -> list[Artifact]:
        """返回所有活跃的印象层节点（常驻注入用）。"""
        arts: list[Artifact] = []
        if self.cache is not None:
            arts = list(self.cache.by_level("impression"))
        if not arts and self.db is not None:
            arts = list(self.db.list("memory", "active"))
        return [
            a
            for a in arts
            if a.header.family == "memory"
            and a.header.state == "active"
            and a.payload.get("level") == "impression"
        ]

    def add_under(self, child: Artifact, parent_id: str | None) -> Artifact:
        """把 child 挂到 parent 下并持久化；parent_id 为 None 时作为根。"""
        if parent_id is not None and parent_id == child.header.id:
            raise ValueError("节点不能挂在自己下面")

        self._persist(child)

        set_parent = getattr(self.db, "set_parent", None)
        if callable(set_parent):
            set_parent(child.header.id, parent_id)
        if parent_id is not None:
            kind = EDGE_PREFIX + parent_id
            self.db.add_edge(parent_id, child.header.id, kind, 1.0)
        return child
