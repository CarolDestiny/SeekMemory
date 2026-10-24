"""test_store：SQLite 持久化、内存缓存与追加日志哈希链。

覆盖 upsert/get 全字段往返、list 过滤、edges 双向查询、账本链连续与
篡改检测，以及 Cache 的 put/get/active/by_level/remove。
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.artifact import Artifact, make, revise
from store.cache import Cache
from store.db import DB
from store.ledger import chain_hash, chain_payload
from store.ledger import Ledger


def _memory(text: str, level: str = "scene", **header_kw: object) -> Artifact:
    """构造一条最小合法 memory，header_kw 原样透传给 make。"""
    payload = {
        "text": text,
        "level": level,
        "shape": "point",
        "chrono": "once",
        "about": "other",
    }
    return make("memory", payload, **header_kw)


def _example() -> Artifact:
    """构造一条最小合法 example。"""
    return make("example", {"user": "你好", "assistant": "嗨"})


def _edges(db: DB, node_id: str) -> list[tuple[str, str, float]]:
    """把边权四舍五入到 6 位，避免浮点比较噪声。"""
    return [(other, kind, round(weight, 6)) for other, kind, weight in db.artifacts.edges_of(node_id)]


class _StoreCase(unittest.TestCase):
    """每个用例一个临时数据库，跑完关闭连接并删除目录。"""

    def setUp(self) -> None:
        """创建临时数据库与缓存。"""
        self.tmpdir = tempfile.mkdtemp(prefix="seekmemory_store_")
        self.db = DB(os.path.join(self.tmpdir, "memory.db"))
        self.cache = Cache(self.db.artifacts)

    def tearDown(self) -> None:
        """关闭数据库并删除临时目录。"""
        self.db.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)


class DBTest(_StoreCase):
    """DB：节点往返、过滤与关系边。"""

    def test_upsert_get_roundtrip_all_fields(self) -> None:
        """upsert 后 get 能无损还原 header 与 payload 的所有字段。"""
        art = make(
            "memory",
            {
                "text": "他加班到很晚", "level": "scene", "shape": "periodic",
                "chrono": "periodic", "about": "relation", "first": True,
            },
            revision=4,
            state="active",
            scope="shared",
            said_by="owner",
            shareable="private_only",
            strength={
                "weight": 2.0, "confidence": 0.9, "arousal": 0.8,
                "valence": -0.5, "funny": 0.3, "hits": 7,
            },
            time={
                "created": "2020-01-01T01:02:03", "updated": "2020-02-03T04:05:06",
                "valid_from": "2020-01-01", "valid_to": "2020-12-31",
                "expires": "2021-01-01",
            },
            lineage={"sources": ("s_1", "s_2"), "derived_from": ("n_x",)},
        )
        self.db.artifacts.upsert(art)
        got = self.db.artifacts.get(art.header.id)
        self.assertIsNotNone(got)
        self.assertEqual(art, got)
        self.assertEqual(got.header.lineage.sources, ("s_1", "s_2"))
        self.assertEqual(got.header.lineage.derived_from, ("n_x",))
        self.assertIsNone(self.db.artifacts.get("n_missing"))

    def test_upsert_updates_existing_row(self) -> None:
        """同 id 再次 upsert 是更新而不是插入，created 保持不变。"""
        art = _memory("旧文本")
        self.db.artifacts.upsert(art)
        revised = revise(art, {"text": "新文本", "level": "detail"}, strength={"weight": 2.5})
        self.db.artifacts.upsert(revised)
        got = self.db.artifacts.get(art.header.id)
        self.assertEqual(got.header.revision, 2)
        self.assertEqual(got.payload["text"], "新文本")
        self.assertEqual(got.payload["level"], "detail")
        self.assertEqual(got.header.strength.weight, 2.5)
        self.assertEqual(got.header.time.created, art.header.time.created)
        self.assertEqual(self.db.artifacts.count("memory"), 1)

    def test_list_filters_family_and_state(self) -> None:
        """list 可按 family、state 单独或组合过滤。"""
        scene = _memory("场景", "scene")
        fact = _memory("事实", "fact")
        example = _example()
        for art in (scene, fact, example):
            self.db.artifacts.upsert(art)
        forgotten = revise(scene, state="forgotten")
        self.db.artifacts.upsert(forgotten)

        self.assertEqual({a.header.id for a in self.db.artifacts.list()}, {scene.header.id, fact.header.id, example.header.id})
        self.assertEqual(
            {a.header.id for a in self.db.artifacts.list(family="memory")},
            {scene.header.id, fact.header.id},
        )
        self.assertEqual(
            {a.header.id for a in self.db.artifacts.list(family="memory", state="active")},
            {fact.header.id},
        )
        self.assertEqual(
            {a.header.id for a in self.db.artifacts.list(family="memory", state="forgotten")},
            {scene.header.id},
        )
        self.assertEqual(len(self.db.artifacts.list(state="active")), 2)
        self.assertEqual(self.db.artifacts.list(family="persona"), [])
        self.assertEqual(self.db.artifacts.count(), 3)
        self.assertEqual(self.db.artifacts.count("memory"), 2)

    def test_edges_of_returns_both_directions(self) -> None:
        """edges_of 从边的任意一端都能查到，另一端与权重正确。"""
        left, right, third = _memory("甲"), _memory("乙"), _memory("丙")
        for art in (left, right, third):
            self.db.artifacts.upsert(art)
        self.db.artifacts.add_edge(left.header.id, right.header.id, "similar", 0.7)
        self.db.artifacts.add_edge(left.header.id, third.header.id, "causal", 0.5)

        self.assertIn((right.header.id, "similar", 0.7), _edges(self.db, left.header.id))
        self.assertIn((third.header.id, "causal", 0.5), _edges(self.db, left.header.id))
        self.assertEqual(_edges(self.db, right.header.id), [(left.header.id, "similar", 0.7)])
        self.assertEqual(_edges(self.db, third.header.id), [(left.header.id, "causal", 0.5)])
        self.assertEqual(_edges(self.db, "n_missing"), [])

        self.db.artifacts.add_edge(left.header.id, right.header.id, "similar", 0.9)
        similar = [edge for edge in _edges(self.db, left.header.id) if edge[0] == right.header.id]
        self.assertEqual(similar, [(right.header.id, "similar", 0.9)])

    def test_ledger_chain_is_continuous(self) -> None:
        """账本从空链开始，逐条 prev 指向上一条 self，整链可验证。"""
        ledger = Ledger(self.db.ledger)
        self.assertTrue(ledger.verify())
        self.assertEqual(ledger.last_hash(), "")

        first = ledger.append("create", "n_1", None, "h_1", "创建")
        second = ledger.append("update", "n_1", "h_1", "h_2", "修改")
        third = ledger.append("forget", "n_2", "h_3", None, "遗忘")
        self.assertEqual(ledger.last_hash(), third)

        entries = self.db.ledger.entries()
        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[0]["prev_hash"], "")
        self.assertEqual(entries[0]["self_hash"], first)
        self.assertEqual(entries[1]["prev_hash"], first)
        self.assertEqual(entries[1]["self_hash"], second)
        self.assertEqual(entries[2]["prev_hash"], second)
        self.assertEqual(entries[2]["self_hash"], third)

        payload = chain_payload(
            str(entries[1]["at"]),
            str(entries[1]["op"]),
            str(entries[1]["entity"]),
            entries[1]["before_hash"],
            entries[1]["after_hash"],
            str(entries[1]["reason"]),
        )
        self.assertEqual(chain_hash(first, payload), second)
        self.assertTrue(ledger.verify())

    def test_ledger_tamper_detected(self) -> None:
        """改动账本任意字段后 verify 返回 False。"""
        ledger = Ledger(self.db.ledger)
        ledger.append("create", "n_1", None, "h_1", "创建")
        ledger.append("update", "n_1", "h_1", "h_2", "修改")
        self.assertTrue(ledger.verify())

        with self.db.conn:
            self.db.conn.execute("UPDATE ledger SET reason = '被改过' WHERE seq = 1")
        self.assertFalse(ledger.verify())

    def test_ledger_prev_tamper_detected(self) -> None:
        """只改 prev_hash 破坏连续性，同样能被检出。"""
        ledger = Ledger(self.db.ledger)
        ledger.append("create", "n_1", None, "h_1", "创建")
        ledger.append("update", "n_1", "h_1", "h_2", "修改")
        with self.db.conn:
            self.db.conn.execute("UPDATE ledger SET prev_hash = 'deadbeef' WHERE seq = 2")
        self.assertFalse(ledger.verify())


class CacheTest(_StoreCase):
    """Cache：热数据索引与移除。"""

    def test_put_get_active_by_level(self) -> None:
        """put 后可 get，active 按 family 过滤，by_level 按 level 过滤。"""
        scene = _memory("场景", "scene")
        fact = _memory("事实", "fact")
        example = _example()
        for art in (scene, fact, example):
            self.cache.put(art)

        self.assertEqual(self.cache.size(), 3)
        self.assertIs(self.cache.get(scene.header.id), scene)
        self.assertEqual(
            {a.header.id for a in self.cache.active()},
            {scene.header.id, fact.header.id, example.header.id},
        )
        self.assertEqual(
            {a.header.id for a in self.cache.active("memory")},
            {scene.header.id, fact.header.id},
        )
        self.assertEqual([a.header.id for a in self.cache.active("example")], [example.header.id])
        self.assertEqual(self.cache.active("persona"), [])
        self.assertEqual([a.header.id for a in self.cache.by_level("scene")], [scene.header.id])
        self.assertEqual([a.header.id for a in self.cache.by_level("fact")], [fact.header.id])
        self.assertEqual(self.cache.by_level("impression"), [])

    def test_put_non_active_removes_from_cache(self) -> None:
        """put 一条非 active 的同 id 记忆时，把它从缓存里移除。"""
        scene = _memory("场景", "scene")
        self.cache.put(scene)
        self.cache.put(revise(scene, state="forgotten"))
        self.assertIsNone(self.cache.get(scene.header.id))
        self.assertEqual(self.cache.size(), 0)
        self.assertEqual(self.cache.by_level("scene"), [])

    def test_put_reindexes_level(self) -> None:
        """同 id 改了 level 后再 put，旧 level 索引会被清理。"""
        art = _memory("场景", "scene")
        self.cache.put(art)
        moved = revise(art, {"text": "细化", "level": "detail"})
        self.cache.put(moved)
        self.assertIs(self.cache.get(art.header.id), moved)
        self.assertEqual(self.cache.by_level("scene"), [])
        self.assertEqual([a.header.id for a in self.cache.by_level("detail")], [art.header.id])

    def test_remove_cleans_indexes(self) -> None:
        """remove 同时清理 family 与 level 索引，重复移除不报错。"""
        scene = _memory("场景", "scene")
        fact = _memory("事实", "fact")
        self.cache.put(scene)
        self.cache.put(fact)
        self.cache.remove(scene.header.id)
        self.assertIsNone(self.cache.get(scene.header.id))
        self.assertEqual(self.cache.size(), 1)
        self.assertEqual(self.cache.by_level("scene"), [])
        self.assertEqual([a.header.id for a in self.cache.active("memory")], [fact.header.id])
        self.cache.remove(scene.header.id)
        self.cache.remove("n_missing")
        self.assertEqual(self.cache.size(), 1)

    def test_load_only_active_from_db(self) -> None:
        """load 清空旧内容，只载入数据库里 state=active 的记忆。"""
        active = _memory("活跃", "scene")
        forgotten = _memory("遗忘", "scene")
        example = _example()
        self.db.artifacts.upsert(active)
        self.db.artifacts.upsert(forgotten)
        self.db.artifacts.upsert(revise(forgotten, state="forgotten"))
        self.db.artifacts.upsert(example)

        stray = _memory("只在缓存里")
        self.cache.put(stray)
        self.cache.load()

        self.assertEqual(
            {a.header.id for a in self.cache.active()},
            {active.header.id, example.header.id},
        )
        self.assertIsNone(self.cache.get(stray.header.id))
        self.assertEqual(self.cache.size(), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
