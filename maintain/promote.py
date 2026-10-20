"""筛选反复被想起的节点，作为人格蒸馏候选返回。"""

from __future__ import annotations

try:  # 作为 astrbot 插件包的一部分导入
    from ..core.artifact import Artifact
    from ..store.cache import Cache
except ImportError:  # 作为顶层包导入（脚本 / 测试）
    from core.artifact import Artifact
    from store.cache import Cache

WEIGHT_BAR = 1.5


def _hits(art: Artifact) -> int:
    """从 header.strength 读取命中次数；缺失或非法时按 0 处理。"""
    raw = getattr(art.header.strength, "hits", 0)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def promote_candidates(cache: Cache, min_hits: int = 10) -> list[Artifact]:
    """返回 weight > 1.5 且 hits > min_hits 的 active 节点，按强度降序。"""
    found = [
        art
        for art in cache.active()
        if art.header.strength.weight > WEIGHT_BAR and _hits(art) > min_hits
    ]
    found.sort(key=lambda art: (art.header.strength.weight, _hits(art)), reverse=True)
    return found
