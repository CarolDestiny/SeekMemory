from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from .artifact import Artifact, content_of
from .source import Source

FULL_MIN = 0.55
PARAPHRASE_MIN = 0.18
HINT_MIN = 0.03

# Continuous priors, not visibility gates. Private memory participates in
# retrieval globally; it is simply less likely to be quoted verbatim.
_SCOPE_PRIOR = {
    "shared": 1.0,
    "private": 0.8,
    "shadow": 0.5,
    "secret": 0.1,
}


class DisclosureLevel(str, Enum):
    FULL = "full"
    PARAPHRASE = "paraphrase"
    HINT = "hint"
    SILENCE = "silence"


@dataclass(frozen=True)
class RecallScene:
    session_id: str
    speaker_id: str
    owner_id: str = ""
    present_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class DisclosureDecision:
    level: DisclosureLevel
    score: float
    reason: str


def scope_prior(art: Artifact) -> float:
    """Return the continuous disclosure prior for a memory scope."""
    scope = str(art.header.scope or "private")
    return _SCOPE_PRIOR.get(scope, 0.4)


def sensitivity_of(art: Artifact) -> float:
    """Legacy sensitivity helper retained for secret/shadow compatibility."""
    if art.header.family == "secret":
        return 1.0
    scope = str(art.header.scope or "private")
    return {"shared": 0.1, "private": 0.2, "shadow": 0.9}.get(scope, 0.4)


def context_affinity(art: Artifact, scene: RecallScene,
                     origin_sessions: Iterable[str] = ()) -> float:
    """How strongly this memory belongs to the current context.

    Session origin is a bonus, not a gate. A private memory can still reach a
    different conversation when its subject is the current speaker.
    """
    origins = {str(x) for x in origin_sessions if x}
    if scene.session_id and scene.session_id in origins:
        return 1.0
    subject = str(art.header.subject_id or "")
    if subject and subject == scene.speaker_id:
        return 0.70
    if subject and subject in scene.present_ids:
        return 0.50
    return 0.22


def audience_overlap(art: Artifact, scene: RecallScene,
                     origin_sessions: Iterable[str] = ()) -> float:
    """Backward-compatible alias for the continuous context factor."""
    return context_affinity(art, scene, origin_sessions)


def subject_fit(art: Artifact, scene: RecallScene) -> float:
    shareable = str(art.header.shareable or "")
    scope = str(art.header.scope or "")
    if shareable == "public":
        return 1.0
    if scope == "shared" and shareable != "secret":
        return 0.8
    subject = str(art.header.subject_id or "")
    if not subject:
        return 0.5
    if subject == scene.speaker_id:
        return 1.0
    if subject == scene.owner_id and subject in scene.present_ids:
        return 0.8
    return 0.35


def exposure(art: Artifact, scene: RecallScene, relevance: float,
             origin_sessions: Iterable[str] = ()) -> float:
    topic = max(0.0, min(1.0, float(relevance)))
    score = context_affinity(art, scene, origin_sessions)
    score *= subject_fit(art, scene)
    score *= scope_prior(art)
    score *= max(0.0, 1.0 - sensitivity_of(art))
    score *= topic
    return max(0.0, min(1.0, score))


def decide(art: Artifact, scene: RecallScene, relevance: float,
           origin_sessions: Iterable[str] = ()) -> DisclosureDecision:
    score = exposure(art, scene, relevance, origin_sessions)
    if score >= FULL_MIN:
        return DisclosureDecision(DisclosureLevel.FULL, score, "high exposure")
    if score >= PARAPHRASE_MIN:
        return DisclosureDecision(DisclosureLevel.PARAPHRASE, score, "partial exposure")
    if score >= HINT_MIN:
        return DisclosureDecision(DisclosureLevel.HINT, score, "low exposure")
    return DisclosureDecision(DisclosureLevel.SILENCE, score, "no exposure")


def decide_source(source: Source, scene: RecallScene) -> DisclosureDecision:
    """Decide whether a Source may contribute raw text or only discovery.

    Raw Source text is origin-scoped: only the exact current session may render
    it. Cross-session user Sources from the current speaker may still lead to
    derived Artifacts but contribute no raw text.
    """
    same_session = bool(
        scene.session_id
        and source.session_id
        and str(source.session_id) == str(scene.session_id)
    )
    if same_session:
        return DisclosureDecision(DisclosureLevel.FULL, 1.0, "same session source")
    if (
        str(source.role or "") == "user"
        and source.speaker_id
        and str(source.speaker_id) == str(scene.speaker_id)
    ):
        return DisclosureDecision(
            DisclosureLevel.HINT, HINT_MIN, "cross-session same-speaker source"
        )
    return DisclosureDecision(DisclosureLevel.SILENCE, 0.0, "source origin isolated")


def safe_text(art: Artifact, level: DisclosureLevel) -> str:
    if level == DisclosureLevel.SILENCE:
        return ""
    if level == DisclosureLevel.HINT:
        return "\u4f60\u9690\u7ea6\u8bb0\u5f97\u6709\u4ef6\u76f8\u5173\u7684\u4e8b\u3002"
    if level == DisclosureLevel.FULL:
        try:
            return content_of(art)
        except Exception:
            return ""
    return "\u4f60\u4e4b\u524d\u63d0\u5230\u8fc7\u4e00\u4ef6\u76f8\u5173\u7684\u4e8b\uff0c\u7ec6\u8282\u8fd9\u91cc\u4e0d\u65b9\u4fbf\u5c55\u5f00\u3002"
