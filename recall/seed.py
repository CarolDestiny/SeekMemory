"""recall.seed：从用户消息里找到最可能唤起记忆的种子节点。"""

from __future__ import annotations

import re

from core.artifact import Artifact, content_of

MEME_WORDS: tuple[str, ...] = ("咕咕嘎嘎", "原神", "鸣潮", "抽象", "哈基米")
MEME_BONUS = 0.75
MEME_BONUS_CAP = 1.5


def bigrams(text: str) -> set[str]:
    """把文本归一化成二元组集合：保留字母数字，忽略标点与空白。"""
    chars = [c.lower() for c in str(text) if c.isalnum()]
    if len(chars) < 2:
        return set(chars)
    return {chars[i] + chars[i + 1] for i in range(len(chars) - 1)}


def overlap(text: str, content: str) -> float:
    """二元组 Dice 重合度：0 表示无关，1 表示完全重合。"""
    a, b = bigrams(text), bigrams(content)
    if not a or not b:
        return 0.0
    return 2.0 * len(a & b) / (len(a) + len(b))


def tags_of(art: Artifact) -> list[str]:
    """取 artifact 的标签，兼容 list 与逗号/空白分隔的字符串。"""
    raw = art.payload.get("tags") or art.payload.get("tag") or []
    if isinstance(raw, str):
        raw = re.split(r"[\s,，#]+", raw)
    return [str(tag).strip().lower() for tag in raw if str(tag).strip()]


def _content(art: Artifact) -> str:
    """content_of 的 fail-open 包装：坏数据不拖垮整次检索。"""
    try:
        return content_of(art)
    except Exception:
        return str(art.payload.get("text") or "")


def seeds(text: str, pool: list[Artifact], limit: int = 5) -> list[str]:
    """
    从用户消息里提取种子节点 id。

    对 pool 中每个 artifact 的 content_of() 做二元组重合度；消息命中
    梗词时，带对应标签的 artifact 额外加分。只返回有信号的前 limit 条。
    """
    if not text or limit <= 0:
        return []
    wanted = [word for word in MEME_WORDS if word in text]
    ranked: list[tuple[float, str]] = []
    for art in pool:
        total = overlap(text, _content(art))
        if wanted:
            tags = tags_of(art)
            hits = sum(1 for word in wanted if any(word in tag for tag in tags))
            total += min(MEME_BONUS_CAP, hits * MEME_BONUS)
        if total > 0:
            ranked.append((total, art.header.id))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [node_id for _, node_id in ranked[:limit]]
