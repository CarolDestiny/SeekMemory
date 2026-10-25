"""Deterministic Dream importance triage tests."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.contracts import DialogueTurn
from perceive.importance import (
    MIN_IMPORTANCE_SCORE,
    rank_topics,
    score_topic,
    select_important_topics,
)


def turn(topic, text, *, session="s", at="2026-10-25T10:00:00", role="user"):
    return DialogueTurn(session, "u1", role, text, at, f"src-{topic}", topic)


class ImportanceScoreTest(unittest.TestCase):
    def test_identity_plan_relationship_and_privacy_are_positive(self):
        self.assertGreaterEqual(
            score_topic([turn("id", "\u6211\u53eb\u5c0f\u660e")])[0], 3
        )
        self.assertGreaterEqual(
            score_topic([turn("plan", "\u4e0b\u5468\u53bb\u676d\u5dde\u51fa\u5dee")])[0],
            3,
        )
        self.assertGreaterEqual(
            score_topic([turn("rel", "\u6211\u5973\u670b\u53cb\u559c\u6b22\u732b")])[0],
            3,
        )
        self.assertGreaterEqual(
            score_topic([turn("private", "\u4e0d\u8981\u544a\u8bc9\u522b\u4eba\u8fd9\u4e2a\u79d8\u5bc6")])[0],
            4,
        )

    def test_greeting_ack_assistant_only_and_emotion_alone_are_low(self):
        self.assertEqual(score_topic([turn("hi", "\u65e9\u5b89")])[0], 0)
        self.assertEqual(
            score_topic([turn("ack", "\u597d\u7684\u8c22\u8c22", role="assistant")])[0],
            0,
        )
        emotion = score_topic([turn("mood", "\u6211\u5f88\u96be\u53d7")])[0]
        self.assertLess(emotion, MIN_IMPORTANCE_SCORE)

    def test_category_dedupe_prevents_keyword_stuffing(self):
        score, reasons = score_topic([
            turn("id", "\u6211\u53eb\u5c0f\u660e\uff0c\u540d\u5b57\u53eb\u5c0f\u660e\uff0c\u6211\u662f\u5b66\u751f")
        ])
        self.assertEqual(score, 3)
        self.assertEqual(reasons.count("identity_profile"), 1)


class ImportanceRankingTest(unittest.TestCase):
    def test_high_value_and_recency_order_with_cap(self):
        items = [
            turn("low", "\u65e9\u5b89", at="2026-10-25T10:00:00"),
            turn("old", "\u4e0b\u5468\u53bb\u51fa\u5dee", at="2026-10-24T10:00:00"),
            turn("new", "\u4e0b\u5468\u53bb\u51fa\u5dee", at="2026-10-25T11:00:00"),
        ]
        ranked = rank_topics(items)
        self.assertEqual(ranked[0].topic_id, "new")
        self.assertGreaterEqual(ranked[0].score, MIN_IMPORTANCE_SCORE)
        selected = select_important_topics(items, cap=1)
        self.assertEqual([item[1] for item in selected], ["new"])

    def test_low_value_topics_are_not_selected(self):
        items = [turn("hi", "\u65e9\u5b89"), turn("ack", "\u597d\u7684")]
        self.assertEqual(select_important_topics(items, cap=10), [])


if __name__ == "__main__":
    unittest.main()
