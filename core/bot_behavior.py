"""机器人自我描述的有限词表；共享文本只从这里生成。"""
from __future__ import annotations

import math

from .artifact import Artifact

SELF_SUBJECT = "bot:self"
MIN_EVIDENCE = 3
MIN_CONFIDENCE = 0.9
BEHAVIOR_TEXT = {
    "respond_emotion": "她先回应情绪，再讨论问题。",
    "clarify_question": "她在信息不足时先澄清问题。",
    "admit_uncertainty": "她承认不确定，不编造答案。",
    "offer_choices": "她提供选择，尊重对方决定。",
    "protect_privacy": "她保护隐私，不透露私人信息。",
    "correct_mistake": "她发现错误后承认并纠正。",
}
BEHAVIORS = tuple(BEHAVIOR_TEXT)


def confident(value: object) -> bool:
    try:
        number = float(value)
    except (ValueError, TypeError):
        return False
    return math.isfinite(number) and MIN_CONFIDENCE <= number <= 1.0


def compose_behaviors(behaviors: list[str]) -> str:
    """拼装固定的第二人称自述，绝不接受自由文本。"""
    return "".join("你" + BEHAVIOR_TEXT[key][1:] for key in behaviors)


def trusted_self_impression(art: Artifact) -> bool:
    p, h = art.payload, art.header
    kind = p.get("bot_behavior")
    return (
        h.family == "memory" and h.state == "active"
        and h.subject_id == SELF_SUBJECT and h.scope == "shared"
        and h.said_by == "inferred" and confident(h.strength.confidence)
        and p.get("level") == "impression" and p.get("about") == "self"
        and isinstance(kind, str) and kind in BEHAVIOR_TEXT
        and p.get("text") == BEHAVIOR_TEXT[kind]
        and len(set(h.lineage.sources)) >= MIN_EVIDENCE + 1
        and bool(h.lineage.derived_from)
        and h.id not in h.lineage.derived_from
    )


def trusted_self_persona(art: Artifact) -> bool:
    """只允许固定安全句式的人格在所有会话里表达。"""
    h, p = art.header, art.payload
    kinds = p.get("behaviors")
    if not isinstance(kinds, list) or not 1 <= len(kinds) <= 3:
        return False
    if any(not isinstance(k, str) or k not in BEHAVIORS for k in kinds):
        return False
    if len(set(kinds)) != len(kinds):
        return False
    return (
        h.family == "persona" and h.state == "active"
        and h.subject_id == SELF_SUBJECT and h.scope == "shared"
        and h.said_by == "inferred" and h.shareable == "public"
        and confident(h.strength.confidence)
        and bool(h.lineage.derived_from)
        and len(set(h.lineage.sources)) >= MIN_EVIDENCE + 1
        and p.get("text") == compose_behaviors(kinds)
    )
