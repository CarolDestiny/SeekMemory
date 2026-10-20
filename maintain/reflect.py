"""纯规则反思：根据用户前后两轮的反应，判断她上一轮说错还是说对。"""

from __future__ import annotations

import re

_NEGATIONS = (
    "不是这个意思",
    "没这么说",
    "我没说",
    "不是",
    "不对",
    "理解错了",
    "说错了",
)
# 疑问式里也含“不是/不对”，先整体剔掉，避免把反问当成明确否定
_QUESTION_FORMS = ("是不是", "对不对", "好不好", "行不行", "能不能", "要不要", "有没有")
_FOLLOWUPS = (
    "然后呢",
    "还有呢",
    "继续",
    "对啊",
    "对的",
    "没错",
    "然后",
    "还有",
    "嗯",
)
# 否定词必须出现在句首或标点/空白之后；句首允许带一个短主语（我不是这个意思）
_NEGATION_RE = re.compile(
    r"(?:^|[。！？!?；;，,、\s])"
    r"(?:我们|你们|他们|她们|我|你|他|她|它)?"
    r"(" + "|".join(re.escape(word) for word in _NEGATIONS) + r")"
)


def _bigrams(text: str) -> set[str]:
    """取规范化字符二元组，用于比较两条消息的字面重合。"""
    plain = re.sub(r"[^\w\u4e00-\u9fff]+", "", text or "").lower()
    if len(plain) < 2:
        return {plain} if plain else set()
    return {plain[i : i + 2] for i in range(len(plain) - 1)}


def _overlap(left: str, right: str) -> float:
    """二元组 Jaccard 重合度，取值 0~1。"""
    a, b = _bigrams(left), _bigrams(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _find_negation(text: str) -> str:
    """返回命中的明确否定词，没命中返回空串。

    先用整句正则匹配：否定词要落在句首或标点之后，且先剔掉“是不是 /
    对不对”这类疑问式，避免裸子串把反问误判成否定。
    """
    cleaned = text
    for form in _QUESTION_FORMS:
        cleaned = cleaned.replace(form, "")
    match = _NEGATION_RE.search(cleaned)
    return match.group(1) if match else ""


def _find_followup(text: str) -> str:
    """返回命中的追问/接话词；先剔掉否定词，避免否定句里的字面误判。"""
    cleaned = text
    for word in _NEGATIONS:
        cleaned = cleaned.replace(word, "")
    for word in _FOLLOWUPS:
        if word in cleaned:
            return word
    return ""


def signals(prev_user: str, cur_user: str) -> dict:
    """按设计第 8 节信号表打分，返回 {"wrong", "right", "reasons"}。"""
    prev = prev_user or ""
    cur = cur_user or ""
    wrong = 0
    right = 0
    reasons: list[str] = []

    negation = _find_negation(cur)
    if negation:
        wrong += 2
        reasons.append(f"明确否定（{negation}）")
    else:
        overlap = _overlap(prev, cur)
        if overlap > 0.6:
            wrong += 1
            reasons.append(f"重复解释同一件事（重合 {overlap:.2f}）")
        followup = _find_followup(cur)
        if followup:
            right += 1
            reasons.append(f"追问/展开（{followup}）")

    if prev and len(cur) < len(prev) * 0.5:
        wrong += 1
        reasons.append(f"回复骤短（{len(cur)} 字 / 上轮 {len(prev)} 字）")

    return {"wrong": wrong, "right": right, "reasons": reasons}


def should_reflect(result: dict) -> bool:
    """错分 ≥ 2 时触发反思。"""
    try:
        return int(result.get("wrong", 0)) >= 2
    except (TypeError, ValueError, AttributeError):
        return False
