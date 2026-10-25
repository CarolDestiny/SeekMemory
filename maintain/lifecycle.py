"""Apply Artifact lifecycle expiry without touching immutable Source rows."""

from __future__ import annotations

import datetime

try:
    from ..core.artifact import Artifact, revise
    from ..store.cache import Cache
    from ..app.ports import ArtifactStore, SourceStore
except ImportError:
    from core.artifact import Artifact, revise
    from store.cache import Cache
    from app.ports import ArtifactStore, SourceStore


def _date(value: str | None) -> datetime.date | None:
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return datetime.date.fromisoformat(value[:10])
    except ValueError:
        return None


def _expired(art: Artifact, today: datetime.date) -> bool:
    deadline = _date(art.header.time.expires) or _date(art.header.time.valid_to)
    return deadline is not None and deadline < today


def forget_expired(artifacts, cache: Cache, today: str = "") -> int:
    """Move expired active Artifacts to forgotten and retain their audit history."""
    try:
        base = datetime.date.fromisoformat(today[:10]) if today else datetime.date.today()
    except ValueError:
        base = datetime.date.today()
    expired = [art for art in list(cache.active()) if _expired(art, base)]
    if not expired:
        return 0
    writes = [
        (revise(art, state="forgotten"), art.header.revision,
         tuple(art.header.lineage.sources))
        for art in expired
    ]
    artifacts.commit_many(writes, op="forget", reason="lifecycle expiration")
    for art in expired:
        cache.remove(art.header.id)
    return len(expired)
