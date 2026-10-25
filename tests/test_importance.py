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
            score_topic([turn("plan", "\u6211\u4e0b\u5468\u53bb\u676d\u5dde\u51fa\u5dee")])[0],
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

    def test_paired_assistant_behavior_and_user_correction_score(self):
        support = [
            turn("support", "\u6211\u8981\u6491\u4e0d\u4f4f"),
            turn("support", "\u6211\u5728\uff0c\u522b\u96be\u8fc7", role="assistant"),
        ]
        score, reasons = score_topic(support)
        self.assertGreaterEqual(score, MIN_IMPORTANCE_SCORE)
        self.assertIn("assistant_behavior", reasons)

        correction = [
            turn("correction", "\u4f60\u7406\u89e3\u9519\u4e86\uff0c\u6211\u8bf4\u7684\u662f\u996d\u540e"),
            turn("correction", "\u62b1\u6b49\uff0c\u6211\u521a\u624d\u8bf4\u9519\u4e86",
                 role="assistant"),
        ]
        score, reasons = score_topic(correction)
        self.assertGreaterEqual(score, MIN_IMPORTANCE_SCORE)
        self.assertIn("user_correction", reasons)
        self.assertIn("assistant_behavior", reasons)

    def test_assistant_only_and_generic_small_talk_score_zero(self):
        self.assertEqual(
            score_topic([turn("support", "\u6211\u5728\uff0c\u522b\u96be\u8fc7",
                              role="assistant")])[0],
            0,
        )
        self.assertEqual(
            score_topic([
                turn("smalltalk", "\u4eca\u5929\u5929\u6c14\u4e0d\u9519"),
                turn("smalltalk", "\u597d\u7684\uff0c\u6536\u5230",
                     role="assistant"),
            ])[0],
            0,
        )

    def test_greeting_ack_assistant_only_and_emotion_alone_are_low(self):
        self.assertEqual(score_topic([turn("hi", "\u65e9\u5b89")])[0], 0)
        self.assertEqual(
            score_topic([turn("ack", "\u597d\u7684\u8c22\u8c22", role="assistant")])[0],
            0,
        )
        emotion = score_topic([turn("mood", "\u6211\u5f88\u96be\u53d7")])[0]
        self.assertLess(emotion, MIN_IMPORTANCE_SCORE)

    def test_known_false_positive_phrases_score_zero(self):
        phrases = (
            "\u660e\u5929\u5929\u6c14\u600e\u4e48\u6837",
            "\u5e2e\u6211\u67e5\u4e00\u4e0b\u5de5\u4f5c\u90ae\u7bb1",
            "\u4f60\u8fd8\u8bb0\u5f97\u6211\u8bf4\u8fc7\u4ec0\u4e48\u5417",
            "\u732b\u597d\u53ef\u7231",
            "\u7238\u5988",
        )
        for phrase in phrases:
            with self.subTest(phrase=phrase):
                self.assertEqual(score_topic([turn("x", phrase)])[0], 0)

    def test_first_person_forms_and_personal_commands_still_score(self):
        phrases = (
            "\u6211\u4e0b\u5468\u53bb\u676d\u5dde\u51fa\u5dee",
            "\u6211\u660e\u5929\u9762\u8bd5",
            "\u6211\u517b\u732b",
            "\u6211\u7238\u4f4f\u9662\u4e86",
            "\u5e2e\u6211\u8bb0\u4f4f\u6211\u559c\u6b22\u732b",
            "\u5e2e\u6211\u67e5\u4e00\u4e0b\u6211\u7684\u5de5\u4f5c\u90ae\u7bb1",
        )
        for phrase in phrases:
            with self.subTest(phrase=phrase):
                self.assertGreaterEqual(
                    score_topic([turn("x", phrase)])[0],
                    MIN_IMPORTANCE_SCORE,
                )

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
            turn("old", "\u6211\u4e0b\u5468\u53bb\u51fa\u5dee", at="2026-10-24T10:00:00"),
            turn("new", "\u6211\u4e0b\u5468\u53bb\u51fa\u5dee", at="2026-10-25T11:00:00"),
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
