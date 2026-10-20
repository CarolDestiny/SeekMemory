"""recall.score：给单条记忆打分，并按分数与探索率选出注入集合。"""

from __future__ import annotations

import math
import random
from datetime import date

try:  # 作为 astrbot 插件包的一部分导入
    from ..core.artifact import Artifact, content_of
    from .seed import overlap, tags_of
except ImportError:  # 作为顶层 recall 包导入（脚本 / 测试）
    from core.artifact import Artifact, content_of
    from recall.seed import overlap, tags_of

POSITIVE = ("开心", "高兴", "喜欢", "哈哈", "笑", "好玩", "可爱", "棒")
NEGATIVE = ("累", "烦", "难过", "委屈", "生气", "难受", "哭", "焦虑", "压力", "孤单", "怕")
ABS_DAYS = 10_000
ORDINAL_DAYS = 500_000
EPOCH_ORDINAL = date(1970, 1, 1).toordinal()


def _content(art: Artifact) -> str:
    """取可读文本，content_of 失败时退回 payload.text。"""
    try:
        return content_of(art)
    except Exception:
        return str(art.payload.get("text") or "")


def _tag_match(text: str, art: Artifact) -> float:
    """标签命中比例，0~1；标签越少，单条命中越值钱。"""
    tags = tags_of(art)
    if not tags:
        return 0.0
    low = text.lower()
    hits = sum(1 for tag in tags if tag in low or overlap(text, tag) >= 0.5)
    return min(1.0, hits / len(tags))


def _emotion_match(text: str, art: Artifact) -> float:
    """消息情绪与记忆强度/效价的贴合度，0~1。"""
    pos = sum(text.count(word) for word in POSITIVE)
    neg = sum(text.count(word) for word in NEGATIVE)
    strength = art.header.strength
    arousal = max(0.0, min(1.0, strength.arousal))
    if not pos and not neg:
        return 0.3 * arousal
    polarity = 1 if pos > neg else -1 if neg > pos else 0
    if polarity == 0 or abs(strength.valence) < 1e-9:
        align = 0.6
    elif polarity * strength.valence > 0:
        align = 1.0
    else:
        align = 0.2
    funny = 0.2 if strength.funny > 0.5 and ("哈哈" in text or "笑" in text) else 0.0
    return min(1.0, align * (0.4 + 0.6 * arousal) + funny)


def _age_days(created: str, now_days: float) -> float:
    """把 now_days 归一成距今天数：0 用 created 算，正小数视为年龄，大数视为绝对天数。"""
    if 0 < now_days < ABS_DAYS:
        return float(now_days)
    try:
        day = date.fromisoformat(str(created)[:10])
    except (TypeError, ValueError):
        return max(0.0, float(now_days)) if now_days < ABS_DAYS else 0.0
    if now_days == 0:
        return max(0.0, (date.today() - day).days)
    base = day.toordinal() if now_days > ORDINAL_DAYS else day.toordinal() - EPOCH_ORDINAL
    return max(0.0, now_days - base)


def _freshness(created: str, now_days: float) -> float:
    """指数新鲜度：当天 1.0，约两周衰减到 0.37。"""
    return math.exp(-_age_days(created, now_days) / 14.0)


def _recently_used(art: Artifact) -> float:
    """最近刚用过返回 1.0，用于 -2.0 惩罚。"""
    payload = art.payload
    try:
        hits = int(payload.get("hits", 0))
    except (TypeError, ValueError):
        hits = 0
    last = payload.get("last_used") or payload.get("hot_until") or payload.get("used_at")
    return 1.0 if hits > 0 and last else 0.0


def score(art: Artifact, text: str, activation: float, now_days: float) -> float:
    """
    单条记忆的综合分（DESIGN 5.1）。

    3.0×字面 + 2.0×标签 + 1.5×情绪 + 1.0×weight
    + 0.5×新鲜度 + 1.5×激活 − 2.0×刚用过。
    """
    strength = art.header.strength
    return (
        3.0 * overlap(text, _content(art))
        + 2.0 * _tag_match(text, art)
        + 1.5 * _emotion_match(text, art)
        + 1.0 * strength.weight
        + 0.5 * _freshness(art.header.time.created, now_days)
        + 1.5 * max(0.0, activation)
        - 2.0 * _recently_used(art)
    )


def select(
    candidates: list[Artifact] | list[tuple[Artifact, float]],
    text: str,
    now_days: float,
    k: int = 8,
    explore: float = 0.1,
    seed: int | str | None = None,
) -> list[Artifact]:
    """
    按分数取 top-k，并以 explore 概率随机捞一条非 top 的记忆做探索。

    candidates 兼容裸 Artifact 与 (Artifact, activation) 二元组；seed
    固定即可复现，不传时用 text 当种子，保证同一条消息选出同一批。
    """
    if k <= 0 or not candidates:
        return []
    pairs = [item if isinstance(item, tuple) else (item, 0.0) for item in candidates]
    ranked = sorted(
        pairs,
        key=lambda pair: (-score(pair[0], text, float(pair[1]), now_days), pair[0].header.id),
    )
    top = [art for art, _ in ranked[:k]]
    rest = ranked[k:]
    if rest and 0.0 < explore <= 1.0:
        rng = random.Random(seed if seed is not None else text)
        if rng.random() < explore:
            pick = rng.choice(rest)[0]
            top = (top[:-1] + [pick]) if len(top) >= k else top + [pick]
    return top
