"""抽取链路的单元测试：缓冲落盘、抽取写库、提示词口径。"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.artifact import content_of  # noqa: E402
from core.graph import Graph  # noqa: E402
from perceive.absorb import absorb, dialogue_of, owner_of, worth_now  # noqa: E402
from perceive.buffer import Buffer  # noqa: E402
from perceive.extract import build_prompt, parse_response  # noqa: E402
from store.cache import Cache  # noqa: E402
from store.db import DB  # noqa: E402


class FakeProvider:
    """假 provider：按预设文本返回，顺便记下收到的提示词。"""

    def __init__(self, text: str, boom: bool = False) -> None:
        self.text = text
        self.boom = boom
        self.seen = ""

    async def text_chat(self, system_prompt: str = "", prompt: str = ""):
        self.seen = prompt
        if self.boom:
            raise RuntimeError("provider down")

        class Resp:
            completion_text = self.text

        return Resp()


def make_db():
    """建一个临时库，返回 (db, cache, graph)。"""
    path = os.path.join(tempfile.mkdtemp(prefix="seekmem_abs_"), "t.db")
    db = DB(path)
    return db, Cache(db), Graph(db, Cache(db))


GOOD = json.dumps([
    {"level": "fact", "text": "他下周三要去杭州出差", "tags": "杭州 出差 下周",
     "about": "world", "arousal": 0.3, "valence": 0.0, "funny": 0.0, "first": True},
    {"level": "impression", "text": "他有点倔，但真有事会帮", "tags": "性格 倔",
     "about": "other", "arousal": 0.4, "valence": 0.3, "funny": 0.2, "first": False},
], ensure_ascii=False)


class BufferTest(unittest.TestCase):
    def test_add_and_take(self):
        buf = Buffer()
        buf.add("umo:a", "第一句")
        buf.add("umo:a", "第二句")
        self.assertEqual(len(buf.items), 2)
        self.assertEqual(len(buf.take()), 2)
        self.assertEqual(buf.items, [])
        buf.add("umo:a", "third", "1", "s_third")
        self.assertEqual(buf.items[0][4], "s_third")

    def test_persist_and_reload(self):
        path = os.path.join(tempfile.mkdtemp(prefix="seekmem_buf_"), "pending.json")
        buf = Buffer(path)
        buf.add("umo:a", "重启别丢")
        again = Buffer(path)
        self.assertEqual(len(again.items), 1)
        self.assertEqual(again.items[0][3], "重启别丢")

    def test_should_flush_needs_idle_and_count(self):
        buf = Buffer()
        buf.add("umo:a", "一")
        self.assertFalse(buf.should_flush(180, 4))  # 条数不够
        for text in ("二", "三", "四"):
            buf.add("umo:a", text)
        self.assertFalse(buf.should_flush(180, 4))  # 时间不够
        buf.last_ts -= 181
        self.assertTrue(buf.should_flush(180, 4))

    def test_broken_file_is_empty(self):
        path = os.path.join(tempfile.mkdtemp(prefix="seekmem_bad_"), "pending.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{不是 json")
        self.assertEqual(Buffer(path).items, [])


class AbsorbTest(unittest.TestCase):
    def test_writes_memories_with_tags(self):
        db, cache, graph = make_db()
        n = asyncio.run(absorb(
            [("umo:a", "10001", "user", "我下周三去杭州出差")], db, cache, graph,
            FakeProvider(GOOD),
        ))
        self.assertEqual(n, 2)
        texts = [content_of(a) for a in cache.active("memory")]
        self.assertTrue(any("杭州" in t for t in texts))
        arts = cache.active("memory")
        self.assertTrue(all(a.payload.get("tags") for a in arts))

    def test_provider_failure_returns_zero(self):
        db, cache, graph = make_db()
        n = asyncio.run(absorb(
            [("umo:a", "10001", "user", "随便说说")], db, cache, graph,
            FakeProvider("", boom=True),
        ))
        self.assertEqual(n, 0)
        self.assertEqual(cache.active("memory"), [])

    def test_bad_items_skipped(self):
        db, cache, graph = make_db()
        n = asyncio.run(absorb(
            [("umo:a", "10001", "user", "说点什么")], db, cache, graph,
            FakeProvider('[{"level": "fact"}, {"level": "fact", "text": "他喜欢猫"}]'),
        ))
        self.assertEqual(n, 1)  # 缺字段的被跳过

    def test_dialogue_and_owner(self):
        items = [("umo:a", "10001", "user", "一"), ("umo:a", "10002", "user", "二")]
        self.assertIn("user(10001): 一", dialogue_of(items))
        self.assertEqual(owner_of(items), "umo:a")
        self.assertEqual(owner_of([("umo:a", "", "user", "一"), ("umo:b", "", "user", "二")]), "")


class WorthNowTest(unittest.TestCase):
    def test_plan_counts(self):
        items = [("umo:a", "10001", "user", "我下周三要去杭州出差")]
        self.assertTrue(worth_now(items))

    def test_fact_counts(self):
        self.assertTrue(worth_now([("umo:a", "1", "user", "我女朋友叫许棠")]))

    def test_strong_emotion_counts(self):
        self.assertTrue(worth_now([("umo:a", "1", "user", "今天差点崩溃")]))

    def test_chitchat_does_not(self):
        items = [("umo:a", "1", "user", "在吗"), ("umo:a", "1", "user", "哈哈"),
                 ("umo:a", "1", "user", "嗯")]
        self.assertFalse(worth_now(items))

    def test_noise_and_own_output_ignored(self):
        items = [("umo:a", "1", "assistant", "我下周要去杭州出差"),
                 ("umo:a", "1", "user", "项目联调有点烦")]
        self.assertFalse(worth_now(items))


class PromptTest(unittest.TestCase):
    def test_prompt_asks_for_facts_and_tags(self):
        prompt = build_prompt([])
        self.assertIn("fact", prompt)
        self.assertIn("tags", prompt)
        self.assertIn("0~6", prompt)

    def test_parse_keeps_tags(self):
        items = parse_response(GOOD)
        self.assertEqual(len(items), 2)
        self.assertIn("杭州", items[0]["tags"])


if __name__ == "__main__":
    unittest.main()
