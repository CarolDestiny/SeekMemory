"""抽取链路的单元测试：缓冲落盘、抽取写库、提示词口径。"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.contracts import DialogueTurn  # noqa: E402
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


def _turn(text, session="umo:a", speaker="10001", source_id="", at=""):
    return DialogueTurn(session, speaker, "user", text, at, source_id)


class BufferTest(unittest.TestCase):
    def test_add_and_take(self):
        buf = Buffer()
        buf.add("umo:a", "第一句")
        buf.add("umo:a", "第二句")
        self.assertEqual(len(buf.items), 2)
        self.assertEqual(len(buf.take()), 2)
        self.assertEqual(buf.items, [])
        buf.add("umo:a", "third", "1", "s_third")
        self.assertEqual(buf.items[0].source_id, "s_third")

    def test_add_accepts_assistant_role(self):
        buf = Buffer()
        turn = buf.add("umo:a", "bot reply", "bot", role="assistant")
        self.assertEqual(turn.role, "assistant")

    def test_topic_grouping_uses_time_and_similarity(self):
        buf = Buffer()
        buf.add("s", "go hangzhou", "1", "s1", "2026-10-20T10:00:00")
        buf.add("s", "hangzhou trip", "1", "s2", "2026-10-20T10:05:00")
        self.assertEqual(buf.items[0].topic_id, buf.items[1].topic_id)
        buf.add("s", "lunch menu", "1", "s3", "2026-10-20T13:00:00")
        self.assertNotEqual(buf.items[1].topic_id, buf.items[2].topic_id)

    def test_persist_and_reload(self):
        path = os.path.join(tempfile.mkdtemp(prefix="seekmem_buf_"), "pending.json")
        buf = Buffer(path)
        buf.add("umo:a", "重启别丢")
        again = Buffer(path)
        self.assertEqual(len(again.items), 1)
        self.assertEqual(again.items[0].text, "重启别丢")

    def test_take_sessions_preserves_other_sessions(self):
        buf = Buffer()
        buf.add("a", "one")
        buf.add("b", "two")
        topic = buf.items[0].topic_id
        taken = buf.take_topics({topic})
        self.assertEqual([row.text for row in taken], ["one"])
        self.assertEqual([row.text for row in buf.items], ["two"])
        buf.restore(taken)
        self.assertEqual(len(buf.items), 2)

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
            [DialogueTurn("umo:a", "10001", "user", "我下周三去杭州出差")], db, cache, graph,
            FakeProvider(GOOD),
        ))
        self.assertEqual(n.written, 2)
        texts = [content_of(a) for a in cache.active("memory")]
        self.assertTrue(any("杭州" in t for t in texts))
        arts = cache.active("memory")
        self.assertTrue(all(a.payload.get("tags") for a in arts))
        self.assertTrue(all(a.header.strength.confidence == 0.5 for a in arts))

    def test_subject_and_event_time_are_preserved(self):
        db, cache, graph = make_db()
        raw = json.dumps([{"level": "fact", "text": "owner has an interview",
                           "tags": "interview work", "subject_kind": "owner",
                           "subject_id": "999", "event_at": "2026-10-20T23:14:00",
                           "valid_from": "2026-10-21"}])
        turn = DialogueTurn("napcat:FriendMessage:999", "999", "user", "interview",
                            "2026-10-20T23:14:00", "s1")
        n = asyncio.run(absorb([turn], db, cache, graph, FakeProvider(raw)))
        self.assertEqual(n.written, 1)
        art = cache.active("memory")[0]
        self.assertEqual(art.header.subject_id, "999")
        self.assertTrue(art.header.time.created.startswith("2026-10-20T23:14:00"))
        self.assertEqual(art.header.time.valid_from, "2026-10-21")

    def test_provider_failure_returns_zero(self):
        db, cache, graph = make_db()
        n = asyncio.run(absorb(
            [DialogueTurn("umo:a", "10001", "user", "随便说说")], db, cache, graph,
            FakeProvider("", boom=True),
        ))
        self.assertEqual(n.written, 0)
        self.assertTrue(n.model_failed)
        self.assertEqual(cache.active("memory"), [])

    def test_bad_items_skipped(self):
        db, cache, graph = make_db()
        n = asyncio.run(absorb(
            [DialogueTurn("umo:a", "10001", "user", "说点什么")], db, cache, graph,
            FakeProvider('[{"level": "fact"}, {"level": "fact", "text": "他喜欢猫"}]'),
        ))
        self.assertEqual(n.written, 1)  # 缺字段的被跳过

    def test_dialogue_and_owner(self):
        items = [DialogueTurn("umo:a", "10001", "user", "一"), DialogueTurn("umo:a", "10002", "user", "二")]
        self.assertIn("user(10001): 一", dialogue_of(items))
        self.assertEqual(owner_of(items), "umo:a")
        self.assertEqual(owner_of([DialogueTurn("umo:a", "", "user", "一"), DialogueTurn("umo:b", "", "user", "二")]), "")


class WorthNowTest(unittest.TestCase):
    def test_plan_counts(self):
        items = [DialogueTurn("umo:a", "10001", "user", "我下周三要去杭州出差")]
        self.assertTrue(worth_now(items))

    def test_fact_counts(self):
        self.assertTrue(worth_now([DialogueTurn("umo:a", "1", "user", "我女朋友叫许棠")]))

    def test_strong_emotion_counts(self):
        self.assertTrue(worth_now([DialogueTurn("umo:a", "1", "user", "今天差点崩溃")]))

    def test_chitchat_does_not(self):
        items = [DialogueTurn("umo:a", "1", "user", "在吗"), DialogueTurn("umo:a", "1", "user", "哈哈"),
                 DialogueTurn("umo:a", "1", "user", "嗯")]
        self.assertFalse(worth_now(items))

    def test_noise_and_own_output_ignored(self):
        items = [DialogueTurn("umo:a", "1", "assistant", "我下周要去杭州出差"),
                 DialogueTurn("umo:a", "1", "user", "项目联调有点烦")]
        self.assertFalse(worth_now(items))


class PromptTest(unittest.TestCase):
    def test_prompt_asks_for_facts_and_tags(self):
        prompt = build_prompt([])
        self.assertIn("fact", prompt)
        self.assertIn("tags", prompt)
        self.assertIn("0~6", prompt)

    def test_prompt_requests_subject_and_event_time(self):
        prompt = build_prompt(["[2026-10-20T23:14:00] user(1): hello"])
        self.assertIn("subject_kind", prompt)
        self.assertIn("subject_id", prompt)
        self.assertIn("event_at", prompt)
        self.assertIn("2026-10-20T23:14:00", prompt)

    def test_parse_keeps_tags(self):
        items = parse_response(GOOD)
        self.assertEqual(len(items), 2)
        self.assertIn("杭州", items[0]["tags"])


if __name__ == "__main__":
    unittest.main()
