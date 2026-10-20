"""test_graph_write：写入时建联想边、边数上限与每周人格沉淀。

覆盖 similar / temporal 自动建边、单节点出度上限与重复写入、persona
规则拼装（第二人称、关键词、来源 lineage、旧版本 merged）、阈值与
建边失败不影响写入（fail-open）。
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.artifact import Artifact, make
from core.graph import Graph
from maintain.link import MAX_EDGES, TEMPORAL_WEIGHT, link_new, persist
from maintain.persona import distill_persona
from recall.assemble import build as assemble
from store.cache import Cache
from store.db import DB
from store.ledger import Ledger


def _memory(
    text: str,
    level: str = "scene",
    weight: float = 1.0,
    hits: int = 0,
    created: str | None = None,
    scope: str = "private",
) -> Artifact:
    """构造一条最小合法 memory；created 不传时由 make 记当前时间。"""
    payload = {
        "text": text,
        "level": level,
        "shape": "pattern" if level == "impression" else "point",
        "chrono": "once",
        "about": "other",
    }
    header = {"strength": {"weight": weight, "hits": hits}, "scope": scope}
    if created is not None:
        header["time"] = {"created": created, "updated": created}
    return make("memory", payload, **header)


class _GraphCase:
    """每个用例一个临时数据库、缓存与关系图。"""

    def setUp(self) -> None:
        """创建临时库与依赖对象。"""
        self.tmpdir = tempfile.mkdtemp(prefix="seekmemory_graph_")
        self.db = DB(os.path.join(self.tmpdir, "memory.db"))
        self.cache = Cache(self.db)
        self.graph = Graph(self.db, self.cache)
        self.ledger = Ledger(self.db)

    def tearDown(self) -> None:
        """关闭数据库并删除临时目录。"""
        self.db.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, art: Artifact) -> Artifact:
        """走生产写入路径：写库 + 建边。"""
        persist(art, self.db, self.cache, self.graph)
        return art

    def _degree(self, node_id: str) -> int:
        """节点的全部边条数。"""
        return len(self.db.edges_of(node_id))


class GraphWriteTest(_GraphCase, unittest.TestCase):
    """写入路径自动建边：similar / temporal、上限与 fail-open。"""

    def test_similar_memory_links_and_is_queryable(self) -> None:
        """写入两条相似记忆后，neighbours 能查到 similar 边。"""
        first = self._write(_memory("他今天加班到凌晨两点才回家"))
        second = self._write(_memory("他今天加班到凌晨两点才回家，很累"))

        neighbours = dict(self.graph.neighbours(second.header.id))
        self.assertIn(first.header.id, neighbours)
        self.assertGreater(neighbours[first.header.id], 0.45)
        similar = [edge for edge in self.db.edges_of(second.header.id)
                   if edge[0] == first.header.id and edge[1] == "similar"]
        self.assertEqual(len(similar), 1)
        self.assertGreater(similar[0][2], 0.45)

    def test_same_day_writes_get_temporal_edge(self) -> None:
        """同一天写入、内容不相似的两条记忆之间是 temporal 边，权重 0.3。"""
        first = self._write(_memory("今天天气不错", created="2026-10-20T09:00:00"))
        second = self._write(_memory("楼下新开了一家面馆", created="2026-10-20T21:00:00"))

        edges = [edge for edge in self.db.edges_of(second.header.id)
                 if edge[0] == first.header.id]
        self.assertEqual(edges, [(first.header.id, "temporal", TEMPORAL_WEIGHT)])

    def test_edge_count_is_capped_and_writes_are_idempotent(self) -> None:
        """连续写入大量相似记忆，每个节点的边数不超过 5，重复建边不增长。"""
        arts = [
            self._write(_memory("他今天又加班到很晚了", created="2026-10-20T20:00:00"))
            for _ in range(8)
        ]
        for art in arts:
            self.assertLessEqual(self._degree(art.header.id), MAX_EDGES)

        before = self._degree(arts[-1].header.id)
        self.assertEqual(link_new(arts[-1], self.graph, self.cache), 0)
        self.assertEqual(link_new(arts[-1], self.graph, self.cache), 0)
        self.assertEqual(self._degree(arts[-1].header.id), before)
        self.assertLessEqual(before, MAX_EDGES)

    def test_edge_failure_does_not_block_write(self) -> None:
        """建边抛异常时记忆仍然写入，persist 不把异常抛给调用方。"""
        class BrokenGraph:
            """link 必然失败的假图，db 仍可读。"""

            def __init__(self, db: DB) -> None:
                self.db = db

            def link(self, *_args) -> None:
                """模拟边写入失败。"""
                raise RuntimeError("edge store down")

        graph = BrokenGraph(self.db)  # type: ignore[arg-type]
        first = make("memory", {"text": "他今天加班", "level": "scene"})
        second = make("memory", {"text": "他今天加班到很晚", "level": "scene"})
        persist(first, self.db, self.cache, graph)  # type: ignore[arg-type]
        persist(second, self.db, self.cache, graph)  # type: ignore[arg-type]

        self.assertIsNotNone(self.db.get(second.header.id))
        self.assertIsNotNone(self.cache.get(second.header.id))
        self.assertEqual(self.db.edges_of(second.header.id), [])


class PersonaTest(_GraphCase, unittest.TestCase):
    """distill_persona：规则拼装、阈值、旧版本合并与账本。"""

    def _seed_impression(self, text: str, weight: float, hits: int,
                         created: str = "2026-10-20T10:00:00") -> Artifact:
        """写入一条 impression 并返回。"""
        return self._write(_memory(text, "impression", weight, hits, created))

    def test_three_stable_impressions_make_second_person_persona(self) -> None:
        """3 条稳定 impression 能沉淀出含关键词的第二人称 persona。"""
        low = self._seed_impression("他偶尔会赖床", 1.2, 1)
        stubborn = self._seed_impression("他有点倔，嘴上不饶人，但真有事会帮", 2.0, 4)
        soft = self._seed_impression("他心软，见不得别人难受", 1.7, 3)
        care = self._seed_impression("他不会照顾自己，经常忘记吃饭", 1.6, 3)
        old = make("persona", {"text": "旧的人格"}, scope="private")
        self.db.upsert(old)
        self.cache.put(old)

        persona = distill_persona(self.db, self.cache, "2026-10-21")
        self.assertIsNotNone(persona)
        assert persona is not None
        text = persona.payload["text"]
        self.assertTrue(text.startswith("你"))
        for keyword in ("倔", "心软", "照顾自己"):
            self.assertIn(keyword, text)
        self.assertEqual(
            persona.header.lineage.derived_from,
            (stubborn.header.id, soft.header.id, care.header.id),
        )
        self.assertNotIn(low.header.id, persona.header.lineage.derived_from)
        self.assertEqual(persona.header.family, "persona")

        active = self.cache.active("persona")
        self.assertEqual([art.header.id for art in active], [persona.header.id])
        stored = self.db.get(old.header.id)
        self.assertIsNotNone(stored)
        self.assertEqual(stored.header.state, "merged")
        self.assertIsNone(self.cache.get(old.header.id))

        entries = self.db.ledger_entries()
        self.assertTrue(any(row["op"] == "merge" for row in entries))
        self.assertTrue(any(persona.header.id in str(row["reason"]) or
                            persona.header.id == row["entity"] for row in entries))
        self.assertTrue(self.ledger.verify())

    def test_threshold_and_age_path(self) -> None:
        """不到阈值不沉淀；存在 30 天以上的高权重 impression 可以沉淀。"""
        self._seed_impression("他最近有点累", 1.6, 1)
        self.assertIsNone(distill_persona(self.db, self.cache, "2026-10-21"))

        aged = self._write(_memory(
            "他不会照顾自己", "impression", 1.6, 0, "2026-08-01T10:00:00"))
        persona = distill_persona(self.db, self.cache, "2026-10-21")
        self.assertIsNotNone(persona)
        assert persona is not None
        self.assertEqual(persona.header.lineage.derived_from, (aged.header.id,))
        self.assertIn("照顾自己", persona.payload["text"])

    def test_no_candidate_keeps_old_persona(self) -> None:
        """没有候选时返回 None，旧 persona 保持 active 且不写新账本。"""
        old = make("persona", {"text": "旧的人格"}, scope="private")
        self.db.upsert(old)
        self.cache.put(old)
        before = len(self.db.ledger_entries())

        self.assertIsNone(distill_persona(self.db, self.cache, "2026-10-21"))
        self.assertEqual(self.db.get(old.header.id).header.state, "active")
        self.assertEqual(len(self.db.ledger_entries()), before)

    def test_persona_is_first_in_assembled_text(self) -> None:
        """组装时 persona 在头部，且不会被补成「你记得你……」。"""
        persona = make("persona", {"text": "你不轻易说重话。"})
        memory = _memory("他加班到很晚", "scene")
        text = assemble([memory, persona], budget=300)
        self.assertTrue(text.startswith("你不轻易说重话。"))
        self.assertNotIn("你记得你", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
