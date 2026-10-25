"""只从有证据的机器人自我印象沉淀稳定编号的人格。"""
from __future__ import annotations

try:
    from ..core.artifact import Artifact, Lineage, Strength, make, revise
    from ..core.bot_behavior import SELF_SUBJECT, compose_behaviors, trusted_self_impression
    from ..app.ports import ArtifactCache, ArtifactStore, SourceStore
    from .self_impression import promote_self_candidates
except ImportError:
    from core.artifact import Artifact, Lineage, Strength, make, revise
    from core.bot_behavior import SELF_SUBJECT, compose_behaviors, trusted_self_impression
    from app.ports import ArtifactCache, ArtifactStore, SourceStore
    from maintain.self_impression import promote_self_candidates

TOP_N = 3


def compose(impressions: list[Artifact]) -> str:
    kinds = list(dict.fromkeys(a.payload["bot_behavior"] for a in impressions
                              if trusted_self_impression(a)))[:TOP_N]
    return compose_behaviors(kinds)


def distill_self_persona(artifacts: ArtifactStore, sources: SourceStore, cache: ArtifactCache,
                        today: str | None = None) -> Artifact | None:
    candidates = promote_self_candidates(cache, sources, today)
    chosen = []
    seen = set()
    for art in candidates:
        kind = art.payload["bot_behavior"]
        if kind not in seen:
            seen.add(kind)
            chosen.append(art)
        if len(chosen) == TOP_N:
            break
    if not chosen:
        return None
    kinds = [a.payload["bot_behavior"] for a in chosen]
    payload = {"text": compose_behaviors(kinds), "behaviors": kinds}
    lineage = Lineage(
        sources=tuple(sorted({s for a in chosen for s in a.header.lineage.sources})),
        derived_from=tuple(a.header.id for a in chosen),
    )
    old = sorted(cache.active("persona"), key=lambda a: (
        a.header.subject_id != SELF_SUBJECT, a.header.time.created, a.header.id))
    base = old[0] if old else None
    strength = Strength(weight=max(a.header.strength.weight for a in chosen),
                        confidence=min(a.header.strength.confidence for a in chosen),
                        hits=sum(a.header.strength.hits for a in chosen))
    kw = dict(subject_id=SELF_SUBJECT, scope="shared", shareable="public",
              said_by="inferred", lineage=lineage, strength=strength)
    unchanged = (base is not None and base.payload == payload
                 and all(getattr(base.header, key) == value for key, value in kw.items()
                         if key != "strength"))
    persona = base if unchanged else (revise(base, payload, **kw) if base
                                     else make("persona", payload, **kw))
    writes = [] if unchanged else [(persona, base.header.revision if base else 0, lineage.sources)]
    retired = [revise(a, state="merged") for a in old[1:]]
    writes.extend((a, a.header.revision - 1, a.header.lineage.sources) for a in retired)
    artifacts.commit_many(writes, op="promote", reason="self-only stable persona and consolidation")
    if writes:
        cache.put(persona)
        for art in retired:
            cache.remove(art.header.id)
    return persona


def distill_persona(artifacts: ArtifactStore, sources: SourceStore, cache: ArtifactCache,
                    today: str | None = None,
                    only_umo: str = "") -> Artifact | None:
    """保留旧签名，但用户印象不再是人格来源。"""
    return distill_self_persona(artifacts, sources, cache, today)
