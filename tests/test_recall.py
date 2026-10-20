"""test_recall：种子提取、候选选择与叙述式组装。

覆盖相关消息能命中对应记忆、select 的 top-k 与确定性、assemble 输出
不是项目符号列表，以及超预算时长度不超过 budget。
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.artifact import Artifact, make
from recall.assemble import build
from recall.score import select
from recall.seed import seeds


def _memory(
    text: str,
    level: str = "scene",
    weight: float = 1.0,
    about: str = "other",
    tags: list[str] | None = None,
) -> Artifact:
    """构造一条 memory，强度与权重可调。"""
    payload: dict[str, object] = {
        "text": text,
        "level": level,
        "shape": "point",
        "chrono": "once",
        "about": about,
    }
    if tags:
        payload["tags"] = tags
    return make(
        "memory",
        payload,
        strength={"weight": weight, "arousal": 0.5, "valence": 0.0},
    )


def _pool() -> list[Artifact]:
    """五条不同话题的记忆，供 seed / select 使用。"""
    return [
        _memory("他今天加班到很晚，回家就睡了"),
        _memory("他的名字叫吕宇轩", "fact"),
        _memory("他说领导今天骂了他一顿", "detail"),
        _memory("周末去吃了火锅，他很开心"),
        _memory("他嘴硬心软，真有事会帮忙", "impression"),
    ]


class _TempDirCase(unittest.TestCase):
    """每个用例一个临时目录，跑完清理（本文件不落盘，仅统一隔离约定）。"""

    def setUp(self) -> None:
        """创建临时目录。"""
        self.tmpdir = tempfile.mkdtemp(prefix="seekmemory_recall_")

    def tearDown(self) -> None:
        """删除临时目录。"""
        shutil.rmtree(self.tmpdir, ignore_errors=True)


class SeedTest(_TempDirCase):
    """seeds：从消息里找最相关的记忆 id。"""

    def test_relevant_message_hits_expected_memory(self) -> None:
        """提到加班的消息命中加班记忆，提到火锅的命中火锅记忆。"""
        pool = _pool()
        overtime = seeds("我今天加班到很晚，好累", pool)
        self.assertTrue(overtime)
        self.assertEqual(overtime[0], pool[0].header.id)

        hotpot = seeds("周末我们去吃火锅吧", pool)
        self.assertTrue(hotpot)
        self.assertEqual(hotpot[0], pool[3].header.id)

    def test_seed_respects_limit(self) -> None:
        """limit 限制返回数量，limit=0 返回空。"""
        pool = _pool()
        text = "我今天加班到很晚，好累"
        self.assertEqual(len(seeds(text, pool, limit=1)), 1)
        self.assertEqual(len(seeds(text, pool, limit=2)), 2)
        self.assertEqual(seeds(text, pool, limit=0), [])
        self.assertEqual(seeds(text, pool, limit=-1), [])

    def test_no_signal_or_empty_text_returns_empty(self) -> None:
        """完全无关的消息和空消息都返回空列表。"""
        pool = _pool()
        self.assertEqual(seeds("", pool), [])
        self.assertEqual(seeds("quantum physics", pool), [])

    def test_meme_tag_adds_bonus(self) -> None:
        """含梗词且带对应标签的记忆会排到前面。"""
        tagged = _memory("今天原神抽卡又歪了", "detail", tags=["原神", "游戏"])
        other = _memory("今天加班到很晚")
        ranked = seeds("原神启动", [other, tagged])
        self.assertTrue(ranked)
        self.assertEqual(ranked[0], tagged.header.id)


class SelectTest(_TempDirCase):
    """select：top-k 数量、确定性与相关度排序。"""

    def test_top_k_count(self) -> None:
        """返回数量为 min(k, 候选数)，k<=0 或空候选返回空。"""
        pool = _pool()
        self.assertEqual(len(select(pool, "加班", 0.0, k=3, explore=0.0)), 3)
        self.assertEqual(len(select(pool, "加班", 0.0, k=5, explore=0.0)), 5)
        self.assertEqual(len(select(pool, "加班", 0.0, k=99, explore=0.0)), 5)
        self.assertEqual(select(pool, "加班", 0.0, k=0, explore=0.0), [])
        self.assertEqual(select([], "加班", 0.0, k=3, explore=0.0), [])

    def test_explore_zero_is_deterministic(self) -> None:
        """explore=0 时同一输入重复调用结果完全一致。"""
        pool = _pool()
        text = "我今天加班到很晚，好累"
        first = [a.header.id for a in select(pool, text, 0.0, k=3, explore=0.0)]
        second = [a.header.id for a in select(pool, text, 0.0, k=3, explore=0.0)]
        third = [
            a.header.id
            for a in select(pool, text, 0.0, k=3, explore=0.0, seed=2026)
        ]
        self.assertEqual(first, second)
        self.assertEqual(first, third)

    def test_most_relevant_ranks_first(self) -> None:
        """最相关的加班记忆排在第一位。"""
        pool = _pool()
        picked = select(pool, "我今天加班到很晚，好累", 0.0, k=3, explore=0.0)
        self.assertEqual(picked[0].header.id, pool[0].header.id)

    def test_select_accepts_activation_pairs(self) -> None:
        """候选可以是 (Artifact, activation) 二元组，激活值参与打分。"""
        pool = _pool()
        candidates = [
            (art, 1.0 if art.header.id == pool[1].header.id else 0.0) for art in pool
        ]
        picked = select(candidates, "quantum", 0.0, k=2, explore=0.0)
        self.assertEqual(len(picked), 2)
        self.assertEqual(picked[0].header.id, pool[1].header.id)

    def test_explore_is_reproducible_with_seed(self) -> None:
        """固定 seed 时探索分支也可复现，且数量仍是 k。"""
        pool = _pool()
        first = [
            a.header.id
            for a in select(pool, "加班", 0.0, k=2, explore=0.5, seed=7)
        ]
        second = [
            a.header.id
            for a in select(pool, "加班", 0.0, k=2, explore=0.5, seed=7)
        ]
        self.assertEqual(first, second)
        self.assertEqual(len(first), 2)


class AssembleTest(_TempDirCase):
    """assemble：叙述化输出、预算裁剪与去重。"""

    def test_output_is_narrative_not_bullets(self) -> None:
        """输出是叙述句，不含换行，也没有行首 "- " 的项目符号。"""
        arts = [
            make("persona", {"text": "我嘴硬心软"}),
            _memory("他加班到很晚", "scene"),
            _memory("他说今天被领导骂了", "detail"),
            make(
                "media",
                {
                    "type": "video",
                    "title": "大肥鱼是怎么来的",
                    "url": "https://x",
                    "summary": "讲大肥鱼由来的视频",
                },
            ),
        ]
        text = build(arts, budget=800)
        self.assertTrue(text.strip())
        self.assertNotIn("\n", text)
        for line in text.splitlines():
            self.assertFalse(line.startswith("- "), f"出现项目符号：{line!r}")
        self.assertTrue(text.endswith("。"))
        self.assertIn("你", text)

    def test_budget_is_respected(self) -> None:
        """超预算时输出长度不超过 budget。"""
        long_persona = make("persona", {"text": "我" * 300})
        memories = [_memory("他最近总是加班到很晚，回家倒头就睡" * 3, "scene") for _ in range(6)]
        arts = [long_persona] + memories
        for budget in (200, 100, 60, 30, 10, 5, 3, 2, 1):
            with self.subTest(budget=budget):
                text = build(arts, budget=budget)
                self.assertLessEqual(len(text), budget)
                self.assertTrue(text)

    def test_empty_or_zero_budget_returns_empty(self) -> None:
        """没有候选或预算非正时返回空串。"""
        arts = [_memory("他加班到很晚")]
        self.assertEqual(build([], budget=100), "")
        self.assertEqual(build(arts, budget=0), "")
        self.assertEqual(build(arts, budget=-10), "")

    def test_duplicate_content_kept_once(self) -> None:
        """完全相同的内容只组装一次。"""
        arts = [
            _memory("他今天加班到很晚"),
            _memory("他今天加班到很晚"),
        ]
        text = build(arts, budget=500)
        self.assertEqual(text.count("加班"), 1)

    def test_secret_and_designated_are_guarded(self) -> None:
        """secret 只给影子句，designated 只说触发提示，不泄露正文。"""
        arts = [
            make("secret", {"ref": "s_1", "shadow_text": "有件事你答应过别人不说"}),
            make("designated", {"text": "密码是 123", "trigger": "那个东西"}),
        ]
        text = build(arts, budget=500)
        self.assertIn("有件事你答应过别人不说", text)
        self.assertIn("那个东西", text)
        self.assertNotIn("密码是 123", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
