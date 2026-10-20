"""test_gate：证据闸门、时钟类问题与旧行为兼容。

覆盖：只有相关性证据（字面 / 标签 / 激活 / 情绪）才能过门，weight 先验不能；
证据的绝对与相对阈值；k 未满返回少量；探索只在过门候选里；时钟类问题不检索
（含反例）；gate=False 保持旧 top-k 行为；空候选与空组装。
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.artifact import Artifact, make
from recall.assemble import build
from recall.gate import MIN_EV_ABS, MIN_EV_REL, evidence_floor, is_clock_query
from recall.score import select


def _memory(text: str, weight: float = 1.0, arousal: float = 0.5,
            level: str = "scene", tags: tuple[str, ...] | None = None,
            created: str | None = None, scope: str = "private") -> Artifact:
    """构造一条 memory；标签、权重、唤醒度与创建日期可调。"""
    payload: dict[str, object] = {"text": text, "level": level, "shape": "point",
                                  "chrono": "once", "about": "other"}
    if tags:
        payload["tags"] = list(tags)
    kwargs: dict[str, object] = {
        "strength": {"weight": weight, "arousal": arousal, "valence": 0.0},
        "scope": scope,
    }
    if created:
        kwargs["time"] = {"created": created, "updated": created}
    return make("memory", payload, **kwargs)


def _low(text: str) -> Artifact:
    """无字面、无标签、零唤醒：只有 weight 先验，证据为 0。"""
    return _memory(text, weight=0.1, arousal=0.0)


class EvidenceGateTest(unittest.TestCase):
    """select(gate=True) 只让有相关性证据的候选过门。"""

    def test_all_low_evidence_returns_empty(self) -> None:
        """候选全是低分低证据时返回空列表，不硬凑 k 条。"""
        pool = [_low("他今天弄了数据库"), _low("他下午在改脚本"), _low("他明天要交报表")]
        self.assertEqual(select(pool, "量子力学", 0.0, k=3, explore=0.0), [])

    def test_weight_prior_alone_cannot_pass(self) -> None:
        """权重 3.0 的高分候选与问句零证据时也不注入（旧行为会进 top-k）。"""
        heavy = _memory("他今天在弄数据库", weight=3.0, arousal=0.2)
        self.assertEqual(select([heavy], "量子力学", 0.0, k=8, explore=0.0), [])
        self.assertEqual(len(select([heavy], "量子力学", 0.0, k=8,
                                    explore=0.0, gate=False)), 1)

    def test_literal_evidence_passes(self) -> None:
        """字面重合是证据：相关记忆被保留，无关低证据候选被过滤。"""
        relevant = _memory("他今天加班到很晚，回家就睡了")
        pool = [relevant, _low("他今天弄了数据库")]
        picked = select(pool, "我今天加班到很晚", 0.0, k=8, explore=0.0)
        self.assertEqual([a.header.id for a in picked], [relevant.header.id])

    def test_tag_evidence_passes(self) -> None:
        """标签命中是证据：正文零字面也能过门（生产记忆必带标签）。"""
        name = _memory("他叫吕宇轩", weight=0.6, arousal=0.1, tags=("名字", "称呼"))
        picked = select([name], "你还记得我名字吗", 0.0, k=8, explore=0.0)
        self.assertEqual([a.header.id for a in picked], [name.header.id])

    def test_activation_evidence_passes(self) -> None:
        """激活值算证据：扩散到的候选即使字面为零也能过门。"""
        linked = _memory("他今天在弄数据库", weight=0.2, arousal=0.0)
        self.assertEqual(select([(linked, 0.0)], "量子力学", 0.0, k=8, explore=0.0), [])
        picked = select([(linked, 1.0)], "量子力学", 0.0, k=8, explore=0.0)
        self.assertEqual([a.header.id for a in picked], [linked.header.id])

    def test_relative_evidence_threshold_filters_weak_match(self) -> None:
        """相对证据阈值：离 top_evidence 太远的弱匹配会被截掉。"""
        strong = _memory("他今天加班到很晚，回家就睡了", weight=1.0, tags=("加班",))
        weak = _memory("他加班", weight=0.8, arousal=0.2)
        text = "我今天加班到很晚，好累"
        loose = select([strong, weak], text, 0.0, k=8, explore=0.0,
                       min_ev_abs=0.0, min_ev_rel=0.0)
        strict = select([strong, weak], text, 0.0, k=8, explore=0.0,
                        min_ev_abs=0.0, min_ev_rel=0.9)
        self.assertEqual(len(loose), 2)
        self.assertEqual([a.header.id for a in strict], [strong.header.id])

    def test_min_ev_abs_drops_below_floor(self) -> None:
        """显式提高绝对证据阈值后，弱证据候选被丢弃、强证据保留。"""
        strong = _memory("他今天加班到很晚，回家就睡了", weight=1.0, tags=("加班",))
        weak = _memory("他加班", weight=0.8, arousal=0.2)
        text = "我今天加班到很晚，好累"
        both = select([strong, weak], text, 0.0, k=8, explore=0.0,
                      min_ev_abs=0.0, min_ev_rel=0.0)
        self.assertEqual(len(both), 2)
        only_strong = select([strong, weak], text, 0.0, k=8, explore=0.0,
                             min_ev_abs=1.5, min_ev_rel=0.0)
        self.assertEqual([a.header.id for a in only_strong], [strong.header.id])

    def test_k_not_full_when_gate_keeps_fewer(self) -> None:
        """过门候选不足 k 时返回实际数量，而不是补满。"""
        pool = [
            _memory("他今天加班到很晚，回家就睡了", weight=1.0, tags=("加班",)),
            _memory("他最近总是加班，很累", weight=1.0, tags=("加班",)),
        ] + [_low(f"他今天在弄{i}号项目") for i in range(4)]
        picked = select(pool, "我今天加班到很晚，好累", 0.0, k=8, explore=0.0)
        self.assertEqual(len(picked), 2)

    def test_gate_false_keeps_legacy_top_k(self) -> None:
        """gate=False 保持旧行为：即使全低证据也凑满 k 条。"""
        pool = [_low(f"他今天弄了{i}号项目") for i in range(5)]
        self.assertEqual(len(select(pool, "量子力学", 0.0, k=3,
                                    explore=0.0, gate=False)), 3)
        self.assertEqual(len(select(pool, "量子力学", 0.0, k=5,
                                    explore=0.0, gate=False)), 5)

    def test_explore_stays_inside_gated_set(self) -> None:
        """探索只从过门候选里捞，不会把低证据噪声带回来。"""
        relevant = _memory("他今天加班到很晚，回家就睡了", weight=1.0, tags=("加班",))
        pool = [relevant] + [_low(f"他今天在弄{i}号项目") for i in range(5)]
        for seed in range(5):
            with self.subTest(seed=seed):
                picked = select(pool, "我今天加班到很晚，好累", 0.0, k=2,
                                explore=1.0, seed=seed)
                self.assertEqual([a.header.id for a in picked], [relevant.header.id])


class ClockQueryTest(unittest.TestCase):
    """时钟类问题交给系统时间，不检索长期记忆。"""

    def test_clock_query_returns_empty(self) -> None:
        """纯问时间的消息直接返回空，即使记忆里字面重合。"""
        memory = _memory("他问今天几号", weight=1.0, arousal=0.0, tags=("琐事",))
        for text in ("今天几号", "今天几号？", "现在几点了", "今天星期几",
                     "今天是几月几号", "几号了"):
            with self.subTest(text=text):
                self.assertEqual(select([memory], text, 0.0, k=8, explore=0.0), [])

    def test_clock_like_but_has_content_is_not_clock(self) -> None:
        """带别的实义词的时间问句不按时钟处理，避免误杀记忆查询。"""
        overtime = _memory("他加班到凌晨两点", weight=1.0, arousal=0.7, tags=("加班",))
        for text in ("今天加班到几点", "我上次加班到几点"):
            with self.subTest(text=text):
                picked = select([overtime], text, 0.0, k=8, explore=0.0)
                self.assertEqual([a.header.id for a in picked], [overtime.header.id])

    def test_is_clock_query_unit(self) -> None:
        """is_clock_query 的正反例直接锁定。"""
        for text in ("今天几号", "现在几点", "今天什么日子", "今天日期"):
            self.assertTrue(is_clock_query(text), text)
        for text in ("今天加班到几点", "今天心情怎么样", "我是不是跟你说过一件事不让说",
                     "", "你觉得我这个人怎么样"):
            self.assertFalse(is_clock_query(text), text)

    def test_gate_false_ignores_clock_gate(self) -> None:
        """gate=False 是旧行为，时钟门也不生效。"""
        memory = _memory("他问今天几号", weight=1.0, arousal=0.0, tags=("琐事",))
        self.assertEqual(len(select([memory], "今天几号", 0.0, k=8,
                                    explore=0.0, gate=False)), 1)


class GateConstantTest(unittest.TestCase):
    """阈值常量与 evidence_floor 的契约。"""

    def test_evidence_floor_is_max_of_abs_and_rel(self) -> None:
        """证据下限取绝对阈值与相对阈值的大者。"""
        self.assertEqual(evidence_floor(0.0), MIN_EV_ABS)
        self.assertAlmostEqual(evidence_floor(10.0), max(MIN_EV_ABS, 10.0 * MIN_EV_REL))
        self.assertAlmostEqual(evidence_floor(10.0, 0.0, 0.5), 5.0)
        self.assertEqual(evidence_floor(1.0, 2.0, 0.0), 2.0)


class EmptyCaseTest(unittest.TestCase):
    """空输入与空组装的边界。"""

    def test_empty_candidates_return_empty(self) -> None:
        """空候选在任何 gate 取值下都返回空。"""
        self.assertEqual(select([], "加班", 0.0, k=8), [])
        self.assertEqual(select([], "加班", 0.0, k=8, gate=False), [])
        self.assertEqual(select([_memory("他加班")], "加班", 0.0, k=0), [])

    def test_build_empty_list_returns_empty_string(self) -> None:
        """assemble.build([]) 返回 ""，不抛错。"""
        self.assertEqual(build([]), "")
        self.assertEqual(build([], budget=0), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
