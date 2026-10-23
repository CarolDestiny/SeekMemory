"""test_maintain：衰减淘汰、反思信号与相似记忆合并。

覆盖低权重旧记忆被标 forgotten、fact 不被淘汰、明确否定/追问两类
反思信号，以及 501 条相似场景合并出 impression 的完整路径。
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.artifact import Artifact, make
from maintain.decay import decay_all
from maintain.merge import merge_similar
from maintain.reflect import signals
from store.cache import Cache
from store.db import DB
from store.ledger import Ledger

OLD_TIME = {"created": "2019-01-01T00:00:00", "updated": "2019-01-01T00:00:00"}
TODAY = "2024-01-02"


def _memory(
    text: str,
    level: str = "scene",
    weight: float = 1.0,
    time: dict[str, str] | None = None,
    **header_kw: object,
) -> Artifact:
    """构造一条 memory；time 不传时用 2019 年的旧时间。"""
    payload = {
        "text": text,
        "level": level,
        "shape": "point",
        "chrono": "once",
        "about": "other",
    }
    return make(
        "memory",
        payload,
        strength={"weight": weight, "arousal": 0.3, "valence": 0.0},
        time=time if time is not None else dict(OLD_TIME),
        **header_kw,
    )


class _MaintainCase(unittest.TestCase):
    """每个用例一个临时数据库，跑完关闭连接并删除目录。"""

    def setUp(self) -> None:
        """创建临时数据库与缓存。"""
        self.tmpdir = tempfile.mkdtemp(prefix="seekmemory_maintain_")
        self.db = DB(os.path.join(self.tmpdir, "memory.db"))
        self.cache = Cache(self.db)
        self.ledger = Ledger(self.db)

    def tearDown(self) -> None:
        """关闭数据库并删除临时目录。"""
        self.db.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _seed(self, art: Artifact) -> None:
        """同时写入数据库和缓存，模拟一条正在使用的记忆。"""
        self.db.upsert(art)
        self.cache.put(art)


class DecayTest(_MaintainCase):
    """decay_all：留存率过低的 active 记忆标 forgotten。"""

    def test_low_weight_old_memory_is_forgotten(self) -> None:
        """低权重且很久没更新的场景应被淘汰并写账本。"""
        art = _memory("很久以前的一件小事", "scene", weight=0.4)
        self._seed(art)

        self.assertEqual(decay_all(self.db, self.cache, TODAY), 1)
        stored = self.db.get(art.header.id)
        self.assertIsNotNone(stored)
        self.assertEqual(stored.header.state, "forgotten")
        self.assertEqual(stored.header.revision, 2)
        self.assertIsNone(self.cache.get(art.header.id))
        self.assertEqual(self.cache.size(), 0)

        entries = self.db.ledger_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[-1]["op"], "forget")
        self.assertEqual(entries[-1]["entity"], art.header.id)
        self.assertIn("retention", str(entries[-1]["reason"]))
        self.assertTrue(self.ledger.verify())

    def test_fact_is_never_eliminated(self) -> None:
        """level=fact 的记忆即使很旧、权重很低也不被淘汰。"""
        fact = _memory("他的名字叫吕宇轩", "fact", weight=0.3)
        scene = _memory("很久以前的一件小事", "scene", weight=0.3)
        self._seed(fact)
        self._seed(scene)

        self.assertEqual(decay_all(self.db, self.cache, TODAY), 1)
        stored = self.db.get(fact.header.id)
        self.assertEqual(stored.header.state, "active")
        self.assertEqual(stored.header.revision, 1)
        self.assertIs(self.cache.get(fact.header.id), fact)
        self.assertEqual(self.db.get(scene.header.id).header.state, "forgotten")

    def test_recent_memory_survives(self) -> None:
        """最近更新过的记忆不会被误伤。"""
        fresh = _memory(
            "昨天发生的事",
            "scene",
            weight=1.0,
            time={"created": "2024-01-01T00:00:00", "updated": "2024-01-01T00:00:00"},
        )
        self._seed(fresh)
        self.assertEqual(decay_all(self.db, self.cache, TODAY), 0)
        self.assertEqual(self.db.get(fresh.header.id).header.state, "active")
        self.assertIsNotNone(self.cache.get(fresh.header.id))

    def test_invalid_today_returns_zero(self) -> None:
        """today 无法解析时不做任何淘汰。"""
        art = _memory("很久以前的一件小事", weight=0.3)
        self._seed(art)
        self.assertEqual(decay_all(self.db, self.cache, "not-a-date"), 0)
        self.assertEqual(self.db.get(art.header.id).header.state, "active")


class ReflectTest(_MaintainCase):
    """signals：明确否定判错，追问/展开判对。"""

    def test_explicit_negation_scores_wrong_at_least_two(self) -> None:
        """「不是这个意思」这类明确否定至少记 2 分错。"""
        result = signals("我今天加班到很晚", "不是这个意思")
        self.assertIsInstance(result, dict)
        self.assertEqual(set(result), {"wrong", "right", "reasons"})
        self.assertGreaterEqual(result["wrong"], 2)
        self.assertIn("明确否定", " ".join(result["reasons"]))

    def test_followup_scores_right_at_least_one(self) -> None:
        """追问/展开/接话至少记 1 分对。"""
        for reply in ("然后呢", "还有呢，继续"):
            with self.subTest(reply=reply):
                result = signals("我今天加班到很晚", reply)
                self.assertGreaterEqual(result["right"], 1)
                self.assertIn("追问", " ".join(result["reasons"]))

    def test_negation_does_not_leak_into_followup(self) -> None:
        """「不对」里的「对」不应被当作追问。"""
        result = signals("我今天加班到很晚", "不对")
        self.assertGreaterEqual(result["wrong"], 2)
        self.assertEqual(result["right"], 0)


class MergeTest(_MaintainCase):
    """merge_similar：超过 500 条时合并最旧一批相似记忆。"""

    def test_merge_rolls_back_when_a_member_write_fails(self) -> None:
        for _ in range(501):
            self._seed(_memory("he works late again", "scene", weight=1.0,
                               time={"created": "2024-01-01T00:00:00",
                                     "updated": "2024-01-01T00:00:00"}))
        before_size = self.cache.size()
        original = self.db._commit_conn
        calls = {"count": 0}

        def flaky(*args, **kwargs):
            calls["count"] += 1
            if calls["count"] == 2:
                raise RuntimeError("member write failed")
            return original(*args, **kwargs)

        self.db._commit_conn = flaky
        with self.assertRaises(RuntimeError):
            merge_similar(self.db, self.cache)
        self.assertEqual(self.cache.size(), before_size)
        self.assertEqual(self.cache.by_level("impression"), [])

    def test_501_similar_scenes_make_impression(self) -> None:
        """501 条相似场景合并出至少一条 impression，成员标 merged。"""
        total = 501
        for _ in range(total):
            self._seed(
                _memory(
                    "他今天又加班到很晚了",
                    "scene",
                    weight=1.0,
                    time={"created": "2024-01-01T00:00:00", "updated": "2024-01-01T00:00:00"},
                )
            )
        self.assertEqual(self.cache.size(), total)

        made = merge_similar(self.db, self.cache)
        self.assertGreaterEqual(made, 1)

        impressions = self.cache.by_level("impression")
        self.assertGreaterEqual(len(impressions), 1)
        impression = impressions[0]
        self.assertEqual(impression.header.family, "memory")
        self.assertEqual(impression.payload["level"], "impression")
        self.assertEqual(impression.payload["shape"], "pattern")
        self.assertEqual(impression.header.said_by, "inferred")
        self.assertIn("经常", impression.payload["text"])
        self.assertGreaterEqual(len(impression.header.lineage.derived_from), 3)
        self.assertGreater(impression.header.strength.weight, 1.0)

        merged = self.db.list(state="merged")
        self.assertGreaterEqual(len(merged), 3)
        self.assertLessEqual(len(merged), 50)
        for member in merged:
            self.assertEqual(member.header.revision, 2)
            self.assertIsNone(self.cache.get(member.header.id))
        self.assertEqual(self.cache.size(), total - len(merged) + made)
        self.assertEqual(self.db.count("memory"), total + made)


if __name__ == "__main__":
    unittest.main(verbosity=2)
