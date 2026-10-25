"""群聊记忆的测试：能不能观察、只看得到本群、不进人格。"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.contracts import DialogueTurn  # noqa: E402
from core.artifact import Strength, make  # noqa: E402
from core.graph import Graph  # noqa: E402
from maintain.persona import distill_persona  # noqa: E402
from maintain.promote import promote_candidates  # noqa: E402
from tests.absorb_support import absorb  # noqa: E402
from perceive.absorb import owner_of  # noqa: E402
from recall.scope import visible  # noqa: E402
from store.cache import Cache  # noqa: E402
from store import open_store  # noqa: E402

GROUP_A = "napcat:GroupMessage:111"
GROUP_B = "napcat:GroupMessage:222"
OWNER = "napcat:FriendMessage:100000000"

PAYLOAD = json.dumps([
    {"level": "fact", "text": "群里有人说周末去爬山", "tags": "爬山 周末 活动",
     "about": "world", "arousal": 0.5, "valence": 0.4, "funny": 0.1, "first": True},
], ensure_ascii=False)


class FakeProvider:
    def __init__(self, text=PAYLOAD):
        self.text = text

    async def text_chat(self, system_prompt="", prompt=""):
        class Resp:
            completion_text = self.text

        return Resp()


def fresh():
    path = os.path.join(tempfile.mkdtemp(prefix="seekmem_grp_"), "t.db")
    db = open_store(path)
    cache = Cache(db.artifacts)
    return db, cache, Graph(db.artifacts)


class GroupWriteTest(unittest.TestCase):
    def test_group_memory_is_shared_by_person(self):
        db, cache, graph = fresh()
        n = asyncio.run(absorb(
            [DialogueTurn(GROUP_A, "10086", "user", "周末有人去爬山吗")], db.artifacts, db.sources, cache, graph,
            FakeProvider()))
        self.assertEqual(n.written, 1)
        art = cache.active("memory")[0]
        # 群聊不是隐私边界：写 shared，归属记说话人
        self.assertEqual(art.header.scope, "shared")
        self.assertEqual(art.header.said_by, "10086")

    def test_multi_speaker_records_all(self):
        db, cache, graph = fresh()
        asyncio.run(absorb(
            [DialogueTurn(GROUP_A, "10086", "user", "周末有人去爬山吗"),
             DialogueTurn(GROUP_A, "10087", "user", "我也想去")], db.artifacts, db.sources, cache, graph,
            FakeProvider()))
        art = cache.active("memory")[0]
        self.assertEqual(art.payload.get("speakers"), ["10086", "10087"])
        self.assertEqual(art.header.said_by, "group")

    def test_owner_of_single_session(self):
        self.assertEqual(owner_of([DialogueTurn(GROUP_A, "1", "user", "a")]), GROUP_A)
        self.assertEqual(owner_of([DialogueTurn(GROUP_A, "1", "user", "a"),
                                   DialogueTurn(GROUP_B, "2", "user", "b")]), "")


class GroupIsolationTest(unittest.TestCase):
    def _pool(self):
        art = make("memory",
                   {"text": "10086 说周末去爬山", "level": "fact"},
                   scope="shared", said_by="10086")
        return [art]

    def test_group_memory_visible_everywhere(self):
        # 群聊不是隐私边界：任何会话都能看到群里的记忆
        pool = self._pool()
        for umo in (GROUP_A, GROUP_B, OWNER):
            self.assertEqual(len(visible(pool, umo, OWNER)), 1, umo)


class PersonaSourceTest(unittest.TestCase):
    def test_group_impressions_not_promoted(self):
        db, cache, _ = fresh()
        group = make("memory",
                     {"text": "群友都挺爱开玩笑", "level": "impression",
                      "owner_umo": GROUP_A},
                     scope="private", strength=Strength(weight=2.0, hits=9))
        owner = make("memory",
                     {"text": "他有点倔", "level": "impression",
                      "owner_umo": OWNER},
                     scope="private", strength=Strength(weight=2.0, hits=9))
        for art in (group, owner):
            db.artifacts.commit(art, expected_revision=0, op="create")
            cache.put(art)
        picked = promote_candidates(cache, db.sources, only_umo=OWNER)
        # GitHub #15：主人和群友的印象都不是机器人自我人格。
        self.assertEqual(picked, [])
        self.assertIsNone(distill_persona(db.artifacts, db.sources, cache, only_umo=OWNER))
        self.assertEqual(cache.active("persona"), [])
        self.assertEqual(db.artifacts.get(owner.header.id), owner)
        self.assertEqual(db.artifacts.get(group.header.id), group)


if __name__ == "__main__":
    unittest.main()
