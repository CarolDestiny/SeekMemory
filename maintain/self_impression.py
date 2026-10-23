"""Deterministic self-impression extraction from bot behavior fields.

This is the first persona-growth step: repeated bot actions become a self-impression,
and only self-impressions are eligible for persona composition.
"""

from __future__ import annotations

import datetime
import re

try:
    from ..core.artifact import Lineage, Strength, TimeSpan, content_of, make
    from ..store.cache import Cache
    from ..store.db import DB
except ImportError:
    from core.artifact import Lineage, Strength, TimeSpan, content_of, make
    from store.cache import Cache
    from store.db import DB

MIN_HITS = 3
SELF_SUBJECT = "bot:self"


def _norm(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def _compose(action: str, tone: str, boundary: str, outcome: str) -> str:
    text = action.strip()
    if not text:
        return ""
    if not text.startswith(("\u5979", "\u4ed6")):
        text = "\u5979" + text
    parts = [text]
    if tone:
        parts.append("\u8bed\u6c14" + tone)
    if boundary:
        parts.append("\u8fb9\u754c\uff1a" + boundary)
    if outcome:
        parts.append("\u7ed3\u679c\uff1a" + outcome)
    return "\uff0c".join(parts).rstrip("\u3002") + "\u3002"


def _behavior(art) -> tuple[str, str, str, str] | None:
    payload = art.payload if isinstance(art.payload, dict) else {}
    action = str(payload.get("bot_action") or "").strip()
    if not action:
        return None
    return (
        action,
        str(payload.get("bot_tone") or "").strip(),
        str(payload.get("bot_boundary") or "").strip(),
        str(payload.get("outcome") or "").strip(),
    )


def build_self_impressions(
    db: DB, cache: Cache, min_hits: int = MIN_HITS, today: str | None = None
) -> int:
    """Aggregate repeated bot behavior into shared self-impression artifacts."""
    groups: dict[tuple[str, str, str, str], list] = {}
    for art in cache.active("memory"):
        behavior = _behavior(art)
        if behavior is None:
            continue
        key = tuple(_norm(part) for part in behavior)
        groups.setdefault(key, []).append(art)

    existing = {
        content_of(art).strip()
        for art in cache.active("memory")
        if str(art.header.subject_id or "") == SELF_SUBJECT
        and str(art.payload.get("level") or "") == "impression"
    }
    made = 0
    stamp = datetime.datetime.now().isoformat(timespec="seconds")
    for key, members in groups.items():
        if len(members) < max(1, int(min_hits)):
            continue
        action, tone, boundary, outcome = key
        text = _compose(action, tone, boundary, outcome)
        if not text or text in existing:
            continue
        sources = tuple(dict.fromkeys(
            source for art in members for source in art.header.lineage.sources
        ))
        art = make(
            "memory",
            {
                "text": text,
                "level": "impression",
                "shape": "pattern",
                "chrono": "once",
                "about": "self",
                "first": False,
                "bot_action": action,
                "bot_tone": tone,
                "bot_boundary": boundary,
                "outcome": outcome,
            },
            scope="shared",
            said_by="inferred",
            subject_id=SELF_SUBJECT,
            strength=Strength(weight=min(3.0, 1.0 + 0.1 * (len(members) - min_hits)),
                              confidence=0.7, hits=len(members)),
            lineage=Lineage(
                sources=sources,
                derived_from=tuple(art.header.id for art in members),
            ),
            time=TimeSpan(created=stamp, updated=stamp),
        )
        db.commit(art, expected_revision=0, op="create",
                  reason="self-impression from repeated bot behavior",
                  source_ids=sources)
        cache.put(art)
        existing.add(text)
        made += 1
    return made


def promote_self_candidates(cache: Cache, today: str | None = None) -> list:
    """Return self-impressions in stable order for persona composition."""
    found = [
        art for art in cache.active("memory")
        if str(art.header.subject_id or "") == SELF_SUBJECT
        and str(art.payload.get("level") or "") == "impression"
        and art.header.state == "active"
    ]
    found.sort(key=lambda art: (art.header.strength.weight,
                                art.header.strength.hits,
                                art.header.id), reverse=True)
    return found
