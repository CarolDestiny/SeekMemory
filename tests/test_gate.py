"""test_gate：select 的相关性双阈值闸门与空注入行为。

覆盖：全低分候选返回空、相关候选不被误杀、相对阈值、gate=False 的旧行为、
探索不越过闸门，以及 assemble.build([]) 返回空串。
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.artifact import Artifact, make
from recall.assemble import build
from recall.score import select


def _memory(text: str, weight: float = 1.0, arousal: float = 0.5,
            level: str = "scene") -> Artifact:
    """构造一条 memory，强度与层级可调。"""
    return make(
        "memory",
        {"text": text, "level": level, "shape": "point", "chrono": "once",
         "about": "other"},
        strength={"weight": weight, "arousal": arousal, "valence": 0.0},
    )


def _low(text: str) -> Artifact:
    """低权重、零唤醒、无标签：综合分只有 weight + freshness，必然低于 1.2。"""
    return _memory(text, weight=0.1, arousal=0.0)


class GateTest(unittest.TestCase):
    """select(gate=True) 的过滤与返回空。"""

    def test_all_low_scores_return_empty(self) -> None:
        """全部候选都低于绝对阈值时返回空列表，而不是硬凑 k 条。"""
        pool = [_low("他今天弄了数据库"), _low("他下午在改脚本"),
                _low("他明天要交报表")]
        self.assertEqual(select(pool, "量子力学", 0.0, k=3, explore=0.0), [])
        # 不传 gate 时默认开启闸门。
        self.assertEqual(select(pool, "量子力学", 0.0, k=3, explore=0.0), [])

    def test_relevant_candidate_survives(self) -> None:
        """高相关候选不会被绝对或相对阈值误杀。"""
        relevant = _memory("他今天加班到很晚，回家就睡了")
        pool = [relevant, _low("他今天弄了数据库"), _low("他下午在改脚本")]
        picked = select(pool, "我今天加班到很晚", 0.0, k=3, explore=0.0)
        self.assertEqual([a.header.id for a in picked], [relevant.header.id])

    def test_relative_threshold_filters_close_scores(self) -> None:
        """过绝对线但低于 top_score × min_rel 的候选仍会被丢弃。"""
        top = _memory("他今天弄了数据库", weight=0.6, arousal=0.0)
        near = _low("他下午在改脚本")
        picked = select([top, near], "量子力学", 0.0, k=8,
                        explore=0.0, min_abs=0.1, min_rel=0.9)
        self.assertEqual([a.header.id for a in picked], [top.header.id])

    def test_gate_false_keeps_legacy_top_k(self) -> None:
        """gate=False 保持旧行为：即使全是低分也凑满 k 条。"""
        pool = [_low(f"他今天弄了{i}号项目") for i in range(5)]
        self.assertEqual(len(select(pool, "量子力学", 0.0, k=3,
                                    explore=0.0, gate=False)), 3)
        self.assertEqual(len(select(pool, "量子力学", 0.0, k=5,
                                    explore=0.0, gate=False)), 5)

    def test_explore_never_adds_gated_candidate(self) -> None:
        """探索只从过闸门的候选里捞，不会把低分噪声带回来。"""
        relevant = _memory("他今天加班到很晚，回家就睡了")
        pool = [relevant] + [_low(f"他今天弄了{i}号项目") for i in range(5)]
        for seed in range(5):
            with self.subTest(seed=seed):
                picked = select(pool, "我今天加班到很晚", 0.0, k=2,
                                explore=1.0, seed=seed)
                self.assertEqual([a.header.id for a in picked],
                                 [relevant.header.id])

    def test_empty_candidates_return_empty(self) -> None:
        """空候选在任何 gate 取值下都返回空。"""
        self.assertEqual(select([], "加班", 0.0, k=8), [])
        self.assertEqual(select([], "加班", 0.0, k=8, gate=False), [])


class EmptyBuildTest(unittest.TestCase):
    """没有相关记忆时，组装必须返回空串而不是占位文本。"""

    def test_build_empty_list_returns_empty_string(self) -> None:
        """assemble.build([]) 返回 ""，不抛错。"""
        self.assertEqual(build([]), "")
        self.assertEqual(build([], budget=0), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
