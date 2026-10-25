"""Pure Source ranking and safe recent-context projection."""

from __future__ import annotations

import datetime
import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Sequence

try:
    from ..app.budget import clamp_chars
    from ..core.disclosure import DisclosureLevel, RecallScene, decide_source
    from ..core.source import Source
    from .intent import intent_of
    from .tokenizer import tokenize
except ImportError:
    from app.budget import clamp_chars
    from core.disclosure import DisclosureLevel, RecallScene, decide_source
    from core.source import Source
    from recall.intent import intent_of
    from recall.tokenizer import tokenize

K1 = 1.2
B = 0.75
CALIBRATION = 8.0
RECENT_PREFIX = "\u6700\u8fd1\u5bf9\u8bdd\uff1a"


@dataclass(frozen=True)
class RankedSource:
    source: Source
    score: float
    lexical: float
    same_session: bool


def _normalise(text: object) -> str:
    return re.sub(r"\s+", "", str(text or "")).casefold()


def _time(value: str) -> datetime.datetime | None:
    try:
        return datetime.datetime.fromisoformat(str(value or "").strip())
    except (TypeError, ValueError):
        return None


def _lexical_scores(query: str, sources: Sequence[Source]) -> dict[str, float]:
    terms = tuple(dict.fromkeys(tokenize(query)))
    if not terms or not sources:
        return {}
    documents: dict[str, Counter[str]] = {}
    lengths: dict[str, int] = {}
    for source in sources:
        tokens = Counter(tokenize(source.text))
        documents[source.id] = tokens
        lengths[source.id] = sum(tokens.values())
    average = sum(lengths.values()) / max(1, len(lengths))
    if average <= 0:
        return {}
    raw: dict[str, float] = {}
    for term in terms:
        matching = [source.id for source in sources if documents[source.id][term]]
        if not matching:
            continue
        df = len(matching)
        idf = math.log1p((len(sources) - df + 0.5) / (df + 0.5))
        for source_id in matching:
            frequency = documents[source_id][term]
            ratio = lengths[source_id] / average
            denominator = frequency + K1 * (1.0 - B + B * ratio)
            raw[source_id] = raw.get(source_id, 0.0) + (
                idf * frequency * (K1 + 1.0) / denominator
            )
    return {
        source_id: value / (value + CALIBRATION)
        for source_id, value in raw.items()
        if value > 0
    }


def rank_recent(
    query: str,
    sources: Iterable[Source],
    *,
    session_id: str = "",
    speaker: str = "",
    limit: int = 0,
    now: datetime.datetime | None = None,
) -> list[RankedSource]:
    """Rank recent Sources with local BM25 plus recency/context signals.

    Explicit recall intent may use recent sources even with weak lexical overlap;
    ordinary queries require a positive lexical match. Clock/greeting/empty
    intent never enters the Source fallback.
    """
    text = str(query or "").strip()
    mode = intent_of(text)
    if not text or mode == "none":
        return []
    rows = [source for source in sources if str(source.text or "").strip()]
    if not rows:
        return []
    query_norm = _normalise(text)
    rows = [source for source in rows if _normalise(source.text) != query_norm]
    lexical = _lexical_scores(text, rows)
    explicit = mode == "loose"
    moment = now or datetime.datetime.now()
    ranked: list[RankedSource] = []
    for source in rows:
        value = float(lexical.get(source.id, 0.0))
        if value <= 0 and not explicit:
            continue
        same_session = bool(
            session_id and str(source.session_id) == str(session_id)
        )
        same_speaker = bool(speaker and str(source.speaker_id) == str(speaker))
        stamp = _time(source.at)
        age_hours = 10_000.0
        if stamp is not None:
            try:
                age_hours = max(0.0, (moment - stamp).total_seconds() / 3600.0)
            except (TypeError, ValueError, OverflowError):
                pass
        recency = 1.0 / (1.0 + age_hours / 12.0)
        score = value * 4.0 + recency * 0.5
        if same_session:
            score += 0.3
        if same_speaker:
            score += 0.1
        ranked.append(RankedSource(source, score, value, same_session))
    ranked.sort(key=lambda row: (-row.score, -row.same_session, row.source.id))
    if limit and limit > 0:
        ranked = ranked[: int(limit)]
    return ranked


def render_same_session(
    candidates: Iterable[RankedSource],
    scene: RecallScene,
    *,
    budget_chars: int,
    protected_source_ids: Iterable[str] = (),
) -> tuple[str, tuple[str, ...]]:
    """Render only raw Source text allowed by the Source disclosure decision.

    Cross-session sources never render raw text. Sources that back protected
    Artifacts are skipped by the caller-supplied protected id set.
    """
    budget = max(0, int(budget_chars))
    if budget <= 0:
        return "", ()
    protected = {str(value) for value in protected_source_ids if value}
    parts: list[str] = []
    seen: set[str] = set()
    used: list[str] = []
    for candidate in candidates:
        source = candidate.source
        if source.id in protected:
            continue
        if decide_source(source, scene).level is not DisclosureLevel.FULL:
            continue
        body = " ".join(str(source.text or "").split())
        if not body or _normalise(body) in seen:
            continue
        prefix = "" if not parts else "\n"
        prefix = RECENT_PREFIX if not parts else prefix
        remaining = budget - len("".join(parts))
        if remaining <= 0:
            break
        piece, _ = clamp_chars(prefix + body, remaining)
        if not piece:
            break
        parts.append(piece)
        seen.add(_normalise(body))
        used.append(str(source.id))
    return "".join(parts), tuple(used)
