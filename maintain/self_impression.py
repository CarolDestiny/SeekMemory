"""用独立的双向对话证据汇总机器人自我印象；不调用模型。"""
from __future__ import annotations

from dataclasses import dataclass

try:
    from ..core.artifact import Artifact, Lineage, Strength, make, revise
    from ..core.bot_behavior import (BEHAVIORS, BEHAVIOR_TEXT, MIN_EVIDENCE,
                                     SELF_SUBJECT, confident, trusted_self_impression)
    from ..core.source import Source
    from ..store.cache import Cache
    from ..store.db import DB
except ImportError:
    from core.artifact import Artifact, Lineage, Strength, make, revise
    from core.bot_behavior import (BEHAVIORS, BEHAVIOR_TEXT, MIN_EVIDENCE,
                                   SELF_SUBJECT, confident, trusted_self_impression)
    from core.source import Source
    from store.cache import Cache
    from store.db import DB

MIN_HITS = MIN_EVIDENCE


def _pairs(ids: tuple[str, ...], sources: dict[str, Source]) -> dict[str, tuple[str, str]]:
    """仅接纳实际存在、同会话且 reply_to 正确的用户/助手对。"""
    result = {}
    for sid in ids:
        assistant = sources.get(sid)
        if assistant is None or assistant.role != "assistant":
            continue
        parent = sources.get(assistant.reply_to or "")
        if (parent is not None and parent.role == "user" and parent.id in ids
                and parent.session_id == assistant.session_id):
            result[sid] = (parent.id, sid)
    return result


@dataclass(frozen=True)
class Observation:
    episode_id: str
    sources: tuple[str, str]
    confidence: float


def _observations(art: Artifact, sources: dict[str, Source]) -> dict[str, Observation]:
    h = art.header
    if (art.payload.get("level") not in ("scene", "detail", "fact")
            or h.lineage.derived_from or not confident(h.strength.confidence)):
        return {}
    pairs = _pairs(h.lineage.sources, sources)
    if len(pairs) != 1 or len(set(h.lineage.sources)) != 2:
        return {}
    return {sid: Observation(h.id, pair, float(h.strength.confidence))
            for sid, pair in pairs.items()}


def _supported(art: Artifact, sources: dict[str, Source]) -> bool:
    return (trusted_self_impression(art)
            and len(_pairs(art.header.lineage.sources, sources)) >= MIN_EVIDENCE)


def build_self_impressions(db: DB, cache: Cache, min_hits: int = MIN_HITS,
                           today: str | None = None) -> int:
    """至少三次独立证据才建立印象；新增证据修订原编号，重跑不重复写。"""
    pool = cache.active("memory")
    ids = sorted({sid for art in pool for sid in art.header.lineage.sources})
    sources = db.sources.sources_by_ids(ids)
    groups: dict[str, dict[str, Observation]] = {key: {} for key in BEHAVIORS}
    old_by_kind: dict[str, Artifact] = {}
    for art in sorted(pool, key=lambda a: a.header.id):
        kind = art.payload.get("bot_behavior")
        if not isinstance(kind, str) or kind not in groups:
            continue
        if _supported(art, sources):
            old_by_kind.setdefault(kind, art)
            # 旧印象只带回原始事件证据，本身不增加计数。
            for episode_id in art.header.lineage.derived_from:
                episode = db.artifacts.get(episode_id)
                if episode is not None and episode.payload.get("bot_behavior") == kind:
                    for sid, observation in _observations(episode, sources).items():
                        groups[kind].setdefault(sid, observation)
        elif art.header.state == "active":
            for sid, observation in _observations(art, sources).items():
                groups[kind].setdefault(sid, observation)
    writes = []
    for kind, observed in groups.items():
        if len(observed) < max(MIN_EVIDENCE, int(min_hits)):
            continue
        observations = [observed[sid] for sid in sorted(observed)]
        lineage = Lineage(
            sources=tuple(dict.fromkeys(s for o in observations for s in o.sources)),
            derived_from=tuple(sorted({o.episode_id for o in observations})),
        )
        payload = {"text": BEHAVIOR_TEXT[kind], "level": "impression",
                   "shape": "pattern", "chrono": "once", "about": "self",
                   "bot_behavior": kind, "first": False}
        strength = Strength(weight=1.5 + min(1.5, 0.1 * (len(observed) - MIN_EVIDENCE)),
                            confidence=min(o.confidence for o in observations),
                            hits=len(observed))
        old = old_by_kind.get(kind)
        if old is not None and old.payload == payload and old.header.lineage == lineage:
            continue
        kw = dict(scope="shared", said_by="inferred", shareable="public",
                  subject_id=SELF_SUBJECT, strength=strength, lineage=lineage)
        art = revise(old, payload=payload, **kw) if old else make("memory", payload, **kw)
        writes.append((art, old.header.revision if old else 0, lineage.sources))
    db.artifacts.commit_many(writes, op="revise", reason="evidence-backed self-impressions")
    for art, _, _ in writes:
        cache.put(art)
    return len(writes)


def promote_self_candidates(cache: Cache, sources, today: str | None = None) -> list[Artifact]:
    pool = [art for art in cache.active("memory") if trusted_self_impression(art)]
    by_id = sources.sources_by_ids(sorted({s for a in pool for s in a.header.lineage.sources}))
    found = [art for art in pool if _supported(art, by_id)]
    found.sort(key=lambda a: (-a.header.strength.weight,
                              BEHAVIORS.index(a.payload["bot_behavior"]), a.header.id))
    return found
