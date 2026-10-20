"""test_strength：留存率、衰减权重、强化与命中冷却。

验证 DESIGN 4.3 的口径：同一条件下重的事记得更久、pattern 比 point
慢、高唤醒负效价最久且低唤醒负效价最快，以及三种强化来源的增量顺序。
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.artifact import Strength
from core.strength import decayed_weight, hit_cooldown_ok, reinforce, retention


def _s(**kw: float) -> Strength:
    """按默认值构造 Strength，只覆盖用例关心的字段。"""
    base = {
        "weight": 1.0,
        "confidence": 1.0,
        "arousal": 0.3,
        "valence": 0.0,
        "funny": 0.0,
        "hits": 0,
    }
    base.update(kw)
    return Strength(**base)


class _TempDirCase(unittest.TestCase):
    """每个用例一个临时目录，跑完清理（本文件纯计算，仅统一隔离约定）。"""

    def setUp(self) -> None:
        """创建临时目录。"""
        self.tmpdir = tempfile.mkdtemp(prefix="seekmemory_strength_")

    def tearDown(self) -> None:
        """删除临时目录。"""
        shutil.rmtree(self.tmpdir, ignore_errors=True)


class RetentionTest(_TempDirCase):
    """retention：留存率随时间下降，并受权重、形状、情绪影响。"""

    def test_retention_basics(self) -> None:
        """当天留存率为 1，之后单调下降且始终落在 (0, 1]。"""
        self.assertAlmostEqual(retention(_s(), "point", 0), 1.0)
        values = [retention(_s(), "point", days) for days in (1, 7, 30, 90, 365)]
        for value in values:
            self.assertGreater(value, 0.0)
            self.assertLessEqual(value, 1.0)
        for earlier, later in zip(values, values[1:]):
            self.assertGreater(earlier, later)

    def test_retention_negative_days_clamped(self) -> None:
        """days 为负按 0 处理，不会出现大于 1 的留存率。"""
        self.assertAlmostEqual(retention(_s(), "point", -10), 1.0)

    def test_unknown_shape_raises(self) -> None:
        """未知形状系数抛 ValueError。"""
        with self.assertRaises(ValueError):
            retention(_s(), "blob", 10)
        with self.assertRaises(ValueError):
            retention(_s(), "", 10)

    def test_heavier_memory_lasts_longer(self) -> None:
        """同一条件下权重大（重要）的事，留存率高于轻的事。"""
        heavy = retention(_s(weight=2.0), "point", 30)
        normal = retention(_s(weight=1.0), "point", 30)
        light = retention(_s(weight=0.4), "point", 30)
        self.assertGreater(heavy, normal)
        self.assertGreater(normal, light)
        self.assertGreater(
            retention(_s(weight=2.0), "point", 60),
            retention(_s(weight=1.0), "point", 60),
        )

    def test_pattern_outlasts_point(self) -> None:
        """形状系数 pattern > span > point。"""
        point = retention(_s(), "point", 30)
        span = retention(_s(), "span", 30)
        pattern = retention(_s(), "pattern", 30)
        self.assertGreater(pattern, point)
        self.assertGreater(span, point)
        self.assertGreater(pattern, span)

    def test_high_arousal_negative_valence_lasts_longest(self) -> None:
        """高唤醒 + 负效价最不容易忘，且高于高唤醒正效价与中性。"""
        values = {
            "high_neg": retention(_s(arousal=0.9, valence=-0.8), "point", 45),
            "high_pos": retention(_s(arousal=0.9, valence=0.8), "point", 45),
            "low_neg": retention(_s(arousal=0.1, valence=-0.8), "point", 45),
            "low_pos": retention(_s(arousal=0.1, valence=0.8), "point", 45),
            "neutral": retention(_s(arousal=0.5, valence=0.0), "point", 45),
        }
        self.assertEqual(max(values, key=values.get), "high_neg")
        self.assertGreater(values["high_neg"], values["high_pos"])
        self.assertGreater(values["high_neg"], values["neutral"])

    def test_low_arousal_negative_valence_forgets_fastest(self) -> None:
        """低唤醒 + 负效价忘得最快，低于低唤醒正效价与中性。"""
        values = {
            "high_neg": retention(_s(arousal=0.9, valence=-0.8), "point", 45),
            "low_neg": retention(_s(arousal=0.1, valence=-0.8), "point", 45),
            "low_pos": retention(_s(arousal=0.1, valence=0.8), "point", 45),
            "neutral": retention(_s(arousal=0.5, valence=0.0), "point", 45),
        }
        self.assertEqual(min(values, key=values.get), "low_neg")
        self.assertLess(values["low_neg"], values["low_pos"])
        self.assertLess(values["low_neg"], values["neutral"])

    def test_decayed_weight(self) -> None:
        """衰减权重 = 原权重 × 留存率，且不超过原权重。"""
        strength = _s(weight=2.0)
        expected = 2.0 * retention(strength, "point", 60)
        self.assertAlmostEqual(decayed_weight(strength, "point", 60), expected)
        self.assertLess(decayed_weight(strength, "point", 60), 2.0)


class ReinforceTest(_TempDirCase):
    """reinforce：三种来源的增量顺序与非法来源报错。"""

    def test_reinforce_deltas_and_order(self) -> None:
        """spoken(+0.3) > confirmed(+0.2) > recall(+0.1)。"""
        base = _s(weight=1.0)
        recall = reinforce(base, "recall")
        confirmed = reinforce(base, "confirmed")
        spoken = reinforce(base, "spoken")
        self.assertAlmostEqual(recall.weight, 1.1)
        self.assertAlmostEqual(confirmed.weight, 1.2)
        self.assertAlmostEqual(spoken.weight, 1.3)
        self.assertGreater(spoken.weight, confirmed.weight)
        self.assertGreater(confirmed.weight, recall.weight)
        self.assertGreater(recall.weight, base.weight)

    def test_reinforce_does_not_mutate_original(self) -> None:
        """Strength 为 frozen dataclass，强化返回新对象。"""
        base = _s(weight=1.0)
        strengthen = reinforce(base, "spoken")
        self.assertIsNot(strengthen, base)
        self.assertAlmostEqual(base.weight, 1.0)
        self.assertAlmostEqual(strengthen.weight, 1.3)

    def test_reinforce_unknown_source_raises(self) -> None:
        """未知强化来源抛 ValueError。"""
        for source in ("seen", "", "SPOKEN"):
            with self.subTest(source=source):
                with self.assertRaises(ValueError):
                    reinforce(_s(), source)


class CooldownTest(_TempDirCase):
    """hit_cooldown_ok：30 分钟窗口内重复命中只计一次。"""

    def test_within_thirty_minutes_not_counted(self) -> None:
        """30 分钟内的重复命中返回 False。"""
        last = "2026-10-21T10:00:00"
        for now in (
            "2026-10-21T10:00:00",
            "2026-10-21T10:01:00",
            "2026-10-21T10:29:59",
        ):
            with self.subTest(now=now):
                self.assertFalse(hit_cooldown_ok(last, now))

    def test_after_thirty_minutes_counted(self) -> None:
        """满 30 分钟及以后返回 True，可以单独计数。"""
        last = "2026-10-21T10:00:00"
        self.assertTrue(hit_cooldown_ok(last, "2026-10-21T10:30:00"))
        self.assertTrue(hit_cooldown_ok(last, "2026-10-21T10:30:01"))
        self.assertTrue(hit_cooldown_ok(last, "2026-10-21T12:00:00"))

    def test_missing_or_invalid_window_allows_count(self) -> None:
        """没有上次窗口或时间解析失败时按可计数处理。"""
        self.assertTrue(hit_cooldown_ok(None, "2026-10-21T10:00:00"))
        self.assertTrue(hit_cooldown_ok("", "2026-10-21T10:00:00"))
        self.assertTrue(hit_cooldown_ok("not-a-time", "2026-10-21T10:00:00"))
        self.assertTrue(hit_cooldown_ok("2026-10-21T10:00:00", "bad-now"))

    def test_timezone_aware_window(self) -> None:
        """带时区的两个时间能正确比较：10 分钟前不计数。"""
        self.assertFalse(
            hit_cooldown_ok(
                "2026-10-21T10:00:00+08:00",
                "2026-10-21T02:10:00+00:00",
            )
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
