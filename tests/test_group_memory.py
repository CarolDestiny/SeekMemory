"""群聊记忆的测试：能不能观察、只看得到本群、不进人格。"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.artifact import Strength, make  # noqa: E402
from core.graph import Graph  # noqa: E402
from maintain.persona import distill_persona  # noqa: E402
from maintain.promote import promote_candidates  # noqa: E402
from perceive.absorb import absorb, owner_of  # noqa: E402
from recall.scope import visible  # noqa: E402
from store.cache import Cache  # noqa: E402
from store.db import DB  # noqa: E402

GROUP_A = "napcat:GroupMessage:111"
GROUP_B = "napcat:GroupMessage:222"
OWNER = "napcat:FriendMessage:2967094107"

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
    db = DB(path)
    cache = Cache(db)
    return db, cache, Graph(db, cache)


class GroupWriteTest(unittest.TestCase):
    def test_group_memory_is_session_private(self):
        db, cache, graph = fresh()
        n = asyncio.run(absorb(
            [(GROUP_A, "10086", "user", "周末有人去爬山吗")], db, cache, graph,
            FakeProvider()))
        self.assertEqual(n, 1)
        art = cache.active("memory")[0]
        self.assertEqual(art.header.scope, "private")
        self.assertEqual(art.payload.get("owner_umo"), GROUP_A)

    def test_owner_of_single_session(self):
        self.assertEqual(owner_of([(GROUP_A, "1", "user", "a")]), GROUP_A)
        self.assertEqual(owner_of([(GROUP_A, "1", "user", "a"),
                                   (GROUP_B, "2", "user", "b")]), "")


class GroupIsolationTest(unittest.TestCase):
    def _pool(self):
        art = make("memory",
                   {"text": "群里有人说周末去爬山", "level": "fact",
                    "owner_umo": GROUP_A},
                   scope="private")
        return [art]

    def test_visible_in_own_group_only(self):
        pool = self._pool()
        self.assertEqual(len(visible(pool, GROUP_A, OWNER)), 1)
        self.assertEqual(len(visible(pool, GROUP_B, OWNER)), 0)
        self.assertEqual(len(visible(pool, OWNER, OWNER)), 0)


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
            db.upsert(art)
            cache.put(art)
        picked = promote_candidates(cache, only_umo=OWNER)
        self.assertEqual([a.header.id for a in picked], [owner.header.id])
        self.assertIsNotNone(distill_persona(db, cache, only_umo=OWNER))
        persona = cache.active("persona")
        self.assertEqual(len(persona), 1)
        self.assertIn("倔", str(persona[0].payload.get("text")))


if __name__ == "__main__":
    unittest.main()
