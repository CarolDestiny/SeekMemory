"""recall.gate：召回闸门的证据阈值与时钟类问题判定。

闸门只看「与这条消息相关」的证据（字面 / 标签 / 激活 / 情绪），
权重先验、新鲜度、刚用过惩罚参与排序但不能单独让记忆过门；
时钟类问题（今天几号/现在几点）交给系统时间，不检索长期记忆。
"""

from __future__ import annotations

# 证据闸门：绝对下限 + 相对最高证据的下限，两条都过才注入。
# 证据量级约 0~4（字面 3 + 标签 2 + 激活 1.5 + 情绪 1.5），标定见 PR-0018。
MIN_EV_ABS = 0.5
MIN_EV_REL = 0.3

# 时钟类问题的标志词：命中其一，且去掉填充词后不剩实义词，才算纯问时间。
CLOCK_MARKERS = ("几号", "几月", "星期", "礼拜", "周几", "几点", "日期",
                 "什么日子", "多少号", "几点了", "几号了")
CLOCK_FILLERS = tuple(sorted((
    "今天", "明天", "昨天", "现在", "当前", "目前", "请问", "问一下",
    "几号", "几月", "几日", "星期", "礼拜", "周几", "几点", "日期",
    "什么日子", "多少号", "多少", "时间", "是", "的", "了", "吗", "呢",
    "啊", "呀", "吧", "么", "那", "这", "号", "日", "几", "点",
), key=len, reverse=True))


def evidence_floor(top_evidence: float,
                   min_abs: float | None = None,
                   min_rel: float | None = None) -> float:
    """过门所需的证据下限：绝对值与「最高证据 × 相对比例」取大。"""
    abs_floor = MIN_EV_ABS if min_abs is None else float(min_abs)
    rel = MIN_EV_REL if min_rel is None else float(min_rel)
    return max(abs_floor, float(top_evidence) * rel)


def is_clock_query(text: str) -> bool:
    """判断是否为纯问时间的短问句；取不到文本或异常一律按「不是」处理。"""
    try:
        raw = "".join(ch for ch in str(text or "") if ch.isalnum())
        if not raw or not any(marker in raw for marker in CLOCK_MARKERS):
            return False
        rest = raw
        for word in CLOCK_FILLERS:
            if word in rest:
                rest = rest.replace(word, "")
        # 允许剩一个语气/单字残渣；剩下实义词说明问题不只是问时间。
        return len(rest) <= 1
    except Exception:  # noqa: BLE001 - 闸门必须 fail-open
        return False
