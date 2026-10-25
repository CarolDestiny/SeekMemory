"""按遗忘曲线衰减所有 active 记忆，把留存率过低的节点标成 forgotten。"""

from __future__ import annotations

import datetime

try:  # 作为 astrbot 插件包的一部分导入
    from ..core.artifact import Artifact, revise
    from ..core.strength import retention
    from ..store.cache import Cache
    from ..app.ports import ArtifactStore
except ImportError:  # 作为顶层包导入（脚本 / 测试）
    from core.artifact import Artifact, revise
    from core.strength import retention
    from store.cache import Cache
    from app.ports import ArtifactStore

FORGET_BELOW = 0.3


def _day(value: str) -> datetime.date | None:
    """把 YYYY-MM-DD 或 ISO 时间的前 10 位解析成日期。"""
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return datetime.date.fromisoformat(value[:10])
    except ValueError:
        return None


def _anchor(art: Artifact) -> datetime.date | None:
    """取最近一次更新日期，没有更新日期就退回创建日期。"""
    span = art.header.time
    return _day(span.updated) or _day(span.created)


def decay_all(artifacts: ArtifactStore, cache: Cache, today: str) -> int:
    base = _day(today)
    if base is None:
        return 0
    expired = []
    for art in list(cache.active()):
        if art.header.family != "memory":
            continue
        anchor = _anchor(art)
        if anchor is None:
            continue
        days = max((base - anchor).days, 0)
        level = str(art.payload.get("level") or "")
        if level == "fact":
            continue
        shape = str(art.payload.get("shape") or "point")
        if retention(art.header.strength, shape, float(days)) >= FORGET_BELOW:
            continue
        expired.append(art)
    if not expired:
        return 0
    writes = [
        (revise(art, state="forgotten"), art.header.revision,
         tuple(art.header.lineage.sources))
        for art in expired
    ]
    artifacts.commit_many(writes, op="forget", reason="retention decay")
    for art in expired:
        cache.remove(art.header.id)
    return len(expired)
