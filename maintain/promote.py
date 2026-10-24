"""兼容的晋升入口；所有调用统一采用机器人自我证据规则。"""
from __future__ import annotations

try:
    from ..core.artifact import Artifact
    from ..store.cache import Cache
except ImportError:
    from core.artifact import Artifact
    from store.cache import Cache
from .self_impression import promote_self_candidates


def promote_candidates(cache: Cache, sources, min_hits: int = 3,
                       today: str | None = None,
                       only_umo: str = "") -> list[Artifact]:
    return [a for a in promote_self_candidates(cache, sources, today)
            if a.header.strength.hits >= max(3, min_hits)]
