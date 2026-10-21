"""调用方式与印象修订的测试：什么时候翻记忆、会不会想起、印象会不会变。"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.artifact import Strength, content_of, make  # noqa: E402
from maintain.impression import revise_impression  # noqa: E402
from recall.drift import best_of, eligible, should_drift  # noqa: E402
from recall.intent import intent_of  # noqa: E402
from store.cache import Cache  # noqa: E402
from store.db import DB  # noqa: E402


def temp_cache():
    """建临时库并返回 (db, cache)。"""
    path = os.path.join(tempfile.mkdtemp(prefix="seekmem_call_"), "t.db")
    db = DB(path)
    return db, Cache(db)


def mem(text, level="scene", weight=1.5, scope="private", arousal=0.4):
    """快速造一条 memory。"""
    return make("memory", {"text": text, "level": level, "tags": "tag"},
                strength=Strength(weight=weight, arousal=arousal), scope=scope)


class IntentTest(unittest.TestCase):
    def test_chitchat_is_none(self):
        for text in ("在吗", "早", "晚安", "吃了吗", "嗯", "哈哈"):
            self.assertEqual(intent_of(text), "none", text)

    def test_clock_is_none(self):
        for text in ("今天几号", "现在几点", "今天星期几"):
            self.assertEqual(intent_of(text), "none", text)

    def test_operation_is_none(self):
        self.assertEqual(intent_of("帮我写个匹配手机号的正则"), "none")

    def test_recall_question_is_loose(self):
        for text in ("你还记得我叫什么吗", "上次那家公司怎么样", "你最了解我什么"):
            self.assertEqual(intent_of(text), "loose", text)

    def test_mood_is_loose(self):
        self.assertEqual(intent_of("我今天好累"), "loose")

    def test_normal_statement_is_strict(self):
        self.assertEqual(intent_of("今天下午三点开会"), "strict")

    def test_duration_question_is_recall(self):
        # 「上次加班到几点」是回忆题，不是问时间
        self.assertEqual(intent_of("我上次加班到几点"), "loose")


class DriftTest(unittest.TestCase):
    def test_eligible_filters(self):
        self.assertTrue(eligible(mem("他养了只猫")))
        self.assertFalse(eligible(mem("别人秘密", scope="shadow")))
        self.assertFalse(eligible(mem("一句话", level="persona")))

    def test_best_of_prefers_heavy_and_recent(self):
        light = mem("最近提过的小事", weight=0.8)
        heavy = mem("他面试过了", weight=2.4, arousal=0.9)
        self.assertIs(best_of([light, heavy], seed=1), heavy)

    def test_best_of_empty(self):
        self.assertIsNone(best_of([], seed=1))

    def test_should_drift_short_only(self):
        self.assertFalse(should_drift("这是一句很长的关于项目进度的说明，不该主动想起什么", seed=1))
        hits = sum(1 for i in range(200) if should_drift("嗯", seed=i))
        self.assertTrue(0 < hits < 80)  # 有概率，但不是必然


class ImpressionTest(unittest.TestCase):
    def test_same_impression_reinforced(self):
        db, cache = temp_cache()
        old = mem("他有点倔，嘴上不饶人", level="impression", weight=1.5)
        db.upsert(old)
        cache.put(old)
        new = mem("他有点倔，嘴上不饶人", level="impression", weight=1.6)
        got = revise_impression(db, cache, new)
        self.assertIsNotNone(got)
        self.assertEqual(got.header.id, old.header.id)
        self.assertEqual(got.header.revision, old.header.revision)
        self.assertGreater(got.header.strength.weight, 1.6)
        self.assertEqual(got.header.strength.hits, 1)

    def test_reworded_impression_new_revision(self):
        db, cache = temp_cache()
        old = mem("他有点倔，嘴上不饶人", level="impression", weight=1.5)
        db.upsert(old)
        cache.put(old)
        new = mem("他有点倔，嘴上不饶人，但真有事会帮", level="impression", weight=1.6)
        got = revise_impression(db, cache, new)
        self.assertIsNotNone(got)
        self.assertEqual(got.header.revision, old.header.revision + 1)
        self.assertIn("真有事会帮", content_of(got))
        self.assertIn(old.header.id, got.header.lineage.derived_from)

    def test_unrelated_impression_untouched(self):
        db, cache = temp_cache()
        old = mem("他有点倔，嘴上不饶人", level="impression")
        db.upsert(old)
        cache.put(old)
        got = revise_impression(db, cache, mem("他很会做饭，做得不错", level="impression"))
        self.assertIsNone(got)

    def test_non_impression_ignored(self):
        db, cache = temp_cache()
        self.assertIsNone(revise_impression(db, cache, mem("他面试过了", level="scene")))


if __name__ == "__main__":
    unittest.main()
