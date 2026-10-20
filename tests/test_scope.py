"""test_scope：scope 过滤、shadow 遮蔽与 designated 交付的回归测试。

对应 ISSUE-0003 / ISSUE-0004。这里直接测纯函数（不导入 main，因为它依赖
astrbot）：recall.scope.visible、recall.assemble.build、recall.designated。
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.artifact import make, revise
from recall.assemble import build
from recall.designated import deliverable, mark_given
from recall.scope import owner_of, visible
from store.cache import Cache
from store.db import DB


def _artifact(text: str, scope: str = "private", **payload):
    """构造一条普通 memory；payload 可带 owner_umo / shadow_text。"""
    payload = {"text": text, "level": "detail", "shape": "point",
               "chrono": "once", "about": "other", **payload}
    return make("memory", payload, scope=scope)


class ScopeTest(unittest.TestCase):
    """visible：private 只给归属会话，shared / shadow 全员可见。"""

    def test_private_visible_only_to_owner_session(self) -> None:
        """A 的 private 不出现在 B 的池子里；shared 与 shadow 两边都在。"""
        owned = _artifact("A 的私聊内容", owner_umo="umo-a")
        legacy = _artifact("没有归属信息的老数据")
        shared = _artifact("共同经历", scope="shared")
        shadow = _artifact("秘密正文", scope="shadow", shadow_text="有件事不能说")
        pool = [owned, legacy, shared, shadow]

        mine = visible(pool, "umo-a", "umo-a")
        self.assertIn(owned, mine)
        self.assertIn(legacy, mine)  # 老数据兜底给 owner 会话
        self.assertIn(shared, mine)
        self.assertIn(shadow, mine)

        guest = visible(pool, "umo-b", "umo-a")
        self.assertNotIn(owned, guest)
        self.assertNotIn(legacy, guest)
        self.assertIn(shared, guest)
        self.assertIn(shadow, guest)

    def test_private_owner_resolved_from_lineage_sources(self) -> None:
        """没有 payload owner 时，用 lineage.sources 反查 sources.umo。"""
        art = make(
            "memory",
            {"text": "从来源推归属", "level": "detail"},
            lineage={"sources": ("s_1",)},
        )
        sources = {"s_1": "umo-a"}
        self.assertEqual(owner_of(art, sources.get), "umo-a")
        self.assertEqual(visible([art], "umo-a", "owner", sources.get), [art])
        self.assertEqual(visible([art], "umo-b", "owner", sources.get), [])

    def test_private_without_owner_hidden_when_no_owner_configured(self) -> None:
        """既无归属信息也没配置 owner_umo 时，private 保守不可见。"""
        art = _artifact("无归属")
        self.assertEqual(visible([art], "", ""), [])
        self.assertEqual(visible([art], "anyone", ""), [])


class ShadowTest(unittest.TestCase):
    """assemble：shadow 只输出影子句，正文永远不出现。"""

    def test_shadow_body_never_in_assemble_output(self) -> None:
        body = "她其实在准备离婚，别告诉任何人"
        art = _artifact(body, scope="shadow", shadow_text="有件事你答应过别人不说")
        for kwargs in ({}, {"text": body, "is_private": True},
                       {"text": body, "is_private": False}):
            with self.subTest(kwargs=kwargs):
                text = build([art], budget=500, **kwargs)
                self.assertNotIn(body, text)
                self.assertIn("有件事你答应过别人不说", text)

    def test_shadow_does_not_mask_normal_memory(self) -> None:
        """shadow 在池子里不影响同一轮正常记忆的注入。"""
        shadow = _artifact("秘密正文", scope="shadow")
        normal = _artifact("他今天加班到很晚")
        text = build([shadow, normal], budget=500)
        self.assertIn("加班", text)
        self.assertNotIn("秘密正文", text)


class DesignatedTest(unittest.TestCase):
    """designated：群聊不注入、私聊无触发不注入、私聊命中才交出正文。"""

    def test_group_never_delivers_body(self) -> None:
        art = make("designated", {"text": "密码是 123", "trigger": "那个东西"})
        text = build([art], budget=500, text="那个东西是什么", is_private=False)
        self.assertEqual(text, "")

    def test_private_without_trigger_not_injected(self) -> None:
        art = make("designated", {"text": "密码是 123", "trigger": "那个东西"})
        text = build([art], budget=500, text="今天吃什么", is_private=True)
        self.assertEqual(text, "")

    def test_private_with_trigger_delivers_full_text(self) -> None:
        art = make("designated", {"text": "密码是 123", "trigger": "那个东西"})
        text = build([art], budget=500, text="你记得那个东西吗", is_private=True)
        self.assertIn("密码是 123", text)
        self.assertIn("可以告诉他", text)

    def test_legacy_context_still_only_hints(self) -> None:
        """不传会话上下文时维持旧行为：只说等提到，不给正文。"""
        art = make("designated", {"text": "密码是 123", "trigger": "那个东西"})
        text = build([art], budget=500)
        self.assertIn("那个东西", text)
        self.assertNotIn("密码是 123", text)

    def test_trigger_list_and_given_state(self) -> None:
        art = make("designated", {"text": "门禁码 8899", "trigger": ["门禁", "那个密码"]})
        self.assertIn("8899", build([art], 500, text="门禁码多少", is_private=True))
        self.assertTrue(deliverable(art, "门禁码多少", True))
        given = revise(art, payload={**art.payload, "given": "2026-10-21T00:00:00"})
        self.assertEqual(build([given], 500, text="门禁", is_private=True), "")


class MarkGivenTest(unittest.TestCase):
    """deliverable + mark_given：交付一次后写回 given，不重复归还。"""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="seekmemory_scope_")
        self.db = DB(os.path.join(self.tmpdir, "scope.db"))
        self.cache = Cache(self.db)

    def tearDown(self) -> None:
        self.db.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_delivery_writes_given_and_stops_redelivery(self) -> None:
        art = make("designated", {"text": "密码是 123", "trigger": "那个东西"})
        self.db.upsert(art)
        self.cache.put(art)

        block = build([art], budget=500, text="那个东西呢", is_private=True)
        self.assertEqual(mark_given(self.db, self.cache, [art], block), 1)

        loaded = self.cache.get(art.header.id)
        self.assertIsNotNone(loaded)
        self.assertTrue(loaded.payload.get("given"))
        self.assertEqual(build([loaded], 500, text="那个东西呢", is_private=True), "")
        self.assertEqual(mark_given(self.db, self.cache, [loaded], block), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
