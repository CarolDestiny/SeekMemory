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

# 常驻层：persona 全部 + 印象层按 weight 取前 N 条（DESIGN 5.3 头部常驻）。
OWNER_SAID_BY = ("owner", "inferred", "")
MAX_PINNED_IMPRESSION = 2

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
                   min_ev_abs: float | None = None,
                   min_ev_rel: float | None = None) -> float:
    """过门所需的证据下限：绝对值与「最高证据 × 相对比例」取大。"""
    abs_floor = MIN_EV_ABS if min_ev_abs is None else float(min_ev_abs)
    rel = MIN_EV_REL if min_ev_rel is None else float(min_ev_rel)
    return max(abs_floor, float(top_evidence) * rel)


def _weight(art) -> float:
    """取权重用于常驻印象层排序；坏数据按 0 处理（fail-open）。"""
    try:
        return float(art.header.strength.weight)
    except Exception:  # noqa: BLE001
        return 0.0


def pinned(cache, subject: str = "") -> list:
    """常驻层：人格全部 + 关于「当前说话的人」的印象前 N 条。

    层级顺序是 人格 > 印象 > 记忆 > 事实。人格是全局底色；印象分人：
    跟谁说话就调出对那个人的印象，不把某人的性格当成对人的总印象。
    这一层不经过证据闸门（它不是检索结果），重复交给 assemble 去重。
    """
    try:
        active = list(cache.active())
    except Exception:  # noqa: BLE001 - 常驻层取不到时不注入，不影响主流程
        return []
    who = str(subject or "")
    allowed = set(OWNER_SAID_BY) if who in ("", "owner") else {who}
    if who:
        allowed.add(who)
    personas, impressions = [], []
    for art in active:
        try:
            if art.header.family == "persona":
                personas.append(art)
            elif (str(art.payload.get("level") or "") == "impression"
                  and str(art.header.said_by or "") in allowed):
                impressions.append(art)
        except Exception:  # noqa: BLE001 - 单条坏数据跳过
            continue
    impressions.sort(key=lambda a: (-_weight(a), a.header.id))
    return personas + impressions[:MAX_PINNED_IMPRESSION]


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
