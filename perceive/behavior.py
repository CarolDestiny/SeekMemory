"""Bot behavior vocabulary shared by the prompt, dedupe and evidence checks.

This module is pure: no storage, no model, no SQL.

The optional payload field is exactly one: ``bot_behavior``. Its value must be
one of the six approved behaviors. The descriptive text fields only describe a
behavior that has already qualified; on their own they never make an item a
behavior item, so they can never feed future self-impression by accident.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

try:
    from ..core.bot_behavior import BEHAVIORS
except ImportError:
    from core.bot_behavior import BEHAVIORS

BEHAVIOR_FIELD = "bot_behavior"
EVIDENCE_FIELD = "evidence_source_ids"
BEHAVIOR_TEXT_FIELDS = ("bot_action", "bot_tone", "bot_boundary", "outcome")

# 六个值就是全部合法取值；其它字符串一律视为构造错误。

# 行为条目没有给 confidence 时的保守默认：低于 0.9，避免伪装高置信。
DEFAULT_BEHAVIOR_CONFIDENCE = 0.6

_SEPARATOR = "\x1e"
_ID_SEPARATOR = "|"


def behavior_of(payload: Mapping[str, Any] | None) -> str:
    """Return the approved behavior value, or an empty string."""
    if not isinstance(payload, Mapping):
        return ""
    value = str(payload.get(BEHAVIOR_FIELD) or "").strip()
    return value if value in BEHAVIORS else ""


def is_behavior(payload: Mapping[str, Any] | None) -> bool:
    """True only when ``bot_behavior`` holds one of the six approved values."""
    return bool(behavior_of(payload))


def check_payload(payload: Mapping[str, Any] | None) -> None:
    """Reject an unknown ``bot_behavior`` value as a construction error."""
    if not isinstance(payload, Mapping):
        raise ValueError("memory payload must be a mapping")
    raw = payload.get(BEHAVIOR_FIELD)
    if raw not in (None, ""):
        if str(raw).strip() not in BEHAVIORS:
            raise ValueError(f"unknown bot_behavior: {raw!r}")


def payload_of(item: Mapping[str, Any]) -> dict[str, Any]:
    """Copy an extracted item for storage without raw evidence or fake behavior.

    Evidence ids belong to lineage and the DB evidence table, not to the memory
    body. Behavior text fields are optional descriptions and are preserved
    individually, but they never qualify an item on their own.
    """
    out = {key: value for key, value in item.items() if key != EVIDENCE_FIELD}
    qualifies = is_behavior(out)
    for key in BEHAVIOR_TEXT_FIELDS:
        value = out.get(key)
        if not isinstance(value, str) or not value.strip():
            out.pop(key, None)
        else:
            out[key] = value.strip()
    if qualifies:
        out[BEHAVIOR_FIELD] = behavior_of(out)
    return out


def evidence_ids(payload: Mapping[str, Any] | None) -> tuple[str, ...]:
    """Return the ordered, de-duplicated evidence ids carried by an item."""
    if not isinstance(payload, Mapping):
        return ()
    raw = payload.get(EVIDENCE_FIELD)
    if isinstance(raw, (str, bytes)) or not isinstance(raw, (list, tuple, set)):
        return ()
    seen: list[str] = []
    for value in raw:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.append(text)
    return tuple(seen)


def behavior_boundary(
    boundary: str, behavior: str, ids: tuple[str, ...] | list[str]
) -> str:
    """Build the identity key of one behavior event.

    The key ignores wording and evidence ordering, so reprocessing the same
    assistant evidence cannot create a duplicate behavior event, while a
    different evidence set stays a distinct event.
    """
    cleaned = sorted({str(value).strip() for value in ids or () if str(value).strip()})
    return f"{boundary}{_SEPARATOR}{behavior}{_SEPARATOR}{_ID_SEPARATOR.join(cleaned)}"


def is_behavior_key(key: str) -> bool:
    """True for a boundary produced by :func:`behavior_boundary`."""
    return _SEPARATOR in str(key or "")


def dedupe_behaviors(
    items: list[dict],
    *,
    existing_keys: set[str],
    boundary_of: Callable[[dict], str],
) -> list[dict]:
    """Drop only re-runs of the same evidence + behavior, never distinct ones."""
    seen = set(existing_keys)
    kept: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if is_behavior(item):
            key = boundary_of(item)
            if key in seen:
                continue
            seen.add(key)
        kept.append(item)
    return kept


def _session_of(turn: Any) -> str:
    return str(getattr(turn, "session_id", "") or "")


def _role_of(turn: Any) -> str:
    return str(getattr(turn, "role", "") or "")


def _reply_to_of(turn: Any) -> str:
    return str(getattr(turn, "reply_to", "") or "")


def validate_evidence(
    payload: Mapping[str, Any],
    available: Mapping[str, Any],
    *,
    session_id: str = "",
) -> tuple[str, ...]:
    """Validate one item's evidence against the Sources actually in this batch.

    Args:
        payload: The extracted item, possibly with ``evidence_source_ids``.
        available: Source id -> turn/Source mapping for the batch plus any
            immutable parents recovered for pairing.
        session_id: The batch session; evidence must not cross it.

    Returns:
        The accepted evidence ids as a tuple (empty for legacy items).

    Raises:
        ValueError: Invented ids, cross-session ids, or a behavior item that
            does not carry at least one assistant turn and its user parent.
    """
    ids = evidence_ids(payload)
    if not ids:
        if is_behavior(payload):
            raise ValueError("bot_behavior item requires evidence_source_ids")
        return ()
    unknown = [value for value in ids if value not in available]
    if unknown:
        raise ValueError("evidence_source_ids not in this batch")
    sessions = {_session_of(available[value]) for value in ids}
    if session_id:
        if any(value != session_id for value in sessions):
            raise ValueError("evidence_source_ids cross session")
    elif len(sessions) > 1:
        raise ValueError("evidence_source_ids cross session")
    if not is_behavior(payload):
        return ids
    if len(ids) != 2:
        raise ValueError("behavior evidence must identify one user/reply pair")
    for value in ids:
        assistant = available[value]
        if _role_of(assistant) != "assistant":
            continue
        parent_id = _reply_to_of(assistant)
        parent = available.get(parent_id) if parent_id else None
        if parent is None or _role_of(parent) != "user":
            continue
        if _session_of(parent) != _session_of(assistant):
            continue
        if parent_id in ids:
            return ids
    raise ValueError("bot_behavior item requires an assistant turn and its user parent")
