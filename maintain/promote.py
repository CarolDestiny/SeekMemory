"""筛选稳定成印象的记忆，作为人格蒸馏候选返回。

稳定的口径（ISSUE-0006）：active、level=impression、weight ≥ 1.5，
并且 hits ≥ 3 或已经存在 ≥ 30 天。纯规则，不调模型。
"""

from __future__ import annotations

import datetime

try:  # 作为 astrbot 插件包的一部分导入
    from ..core.artifact import Artifact
    from ..store.cache import Cache
except ImportError:  # 作为顶层包导入（脚本 / 测试）
    from core.artifact import Artifact
    from store.cache import Cache

WEIGHT_BAR = 1.5
HITS_BAR = 3
AGE_DAYS = 30
LEVEL = "impression"


def _hits(art: Artifact) -> int:
    """命中次数：优先 header.strength.hits，旧数据回退 payload["hits"]。"""
    for raw in (getattr(art.header.strength, "hits", 0), art.payload.get("hits")):
        try:
            value = max(0, int(raw or 0))
        except (TypeError, ValueError):
            continue
        if value:
            return value
    return 0


def _from(art: Artifact, umo: str) -> bool:
    """这条记忆是不是来自指定会话：人格沉淀只吃主人私聊的印象。"""
    payload = art.payload if isinstance(art.payload, dict) else {}
    if str(payload.get("owner_umo") or payload.get("umo") or "") != umo:
        return False
    return str(art.header.scope) == "private"


def _age_days(art: Artifact, today: datetime.date) -> int:
    """按创建时间算存在天数；时间缺失或非法时按 0 天。"""
    raw = art.header.time.created or art.header.time.updated
    try:
        day = datetime.date.fromisoformat(str(raw)[:10])
    except (TypeError, ValueError):
        return 0
    return max(0, (today - day).days)


def promote_candidates(
    cache: Cache,
    min_hits: int = HITS_BAR,
    today: str | None = None,
    only_umo: str = "",
) -> list[Artifact]:
    """返回稳定 impression，按 weight、hits 降序；阈值不满足时返回空。"""
    try:
        base = datetime.date.fromisoformat(str(today)[:10]) if today else None
    except ValueError:
        base = None
    base = base or datetime.date.today()
    found = [
        art
        for art in cache.active()
        if not only_umo or _from(art, only_umo)
        if art.header.family == "memory"
        and art.header.state == "active"
        and str(art.payload.get("level") or "") == LEVEL
        and float(art.header.strength.weight) >= WEIGHT_BAR
        and (_hits(art) >= min_hits or _age_days(art, base) >= AGE_DAYS)
    ]
    found.sort(key=lambda art: (art.header.strength.weight, _hits(art)), reverse=True)
    return found
