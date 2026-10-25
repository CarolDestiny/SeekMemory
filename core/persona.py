"""Persona file schema and pure helpers for one-time persona bootstrap.

A persona file is authored content for the single active persona chain.  It is
not a Source and it is not chat evidence.  The bootstrap helper only converts a
validated file into the payload of the initial persona Artifact.  Recall and
trust decisions stay in their existing owners.
"""
from __future__ import annotations

import json
import re
from typing import Any

PERSONA_ORIGIN_SEED = "seed"
PERSONA_ORIGIN_DREAM = "dream"
PERSONA_ORIGINS = (PERSONA_ORIGIN_SEED, PERSONA_ORIGIN_DREAM)
_SEED_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
_MAX_TEXT = 20000
_MAX_STYLE = 20000
_MAX_BOUNDARIES = 32
_MAX_BOUNDARY = 300
_MAX_EXAMPLES = 32


def _text(value: object, field: str, *, maximum: int, required: bool = False) -> str:
    if not isinstance(value, str):
        if required:
            raise ValueError(f"persona 文件缺少字符串字段：{field}")
        return ""
    text = value.strip()
    if required and not text:
        raise ValueError(f"persona 文件字段不能为空：{field}")
    if len(text) > maximum:
        raise ValueError(f"persona 文件字段过长：{field}")
    return text


def _json_object(value: object, field: str, *, maximum: int) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"persona 文件字段必须是对象：{field}")
    try:
        encoded = json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"persona 文件字段无法序列化：{field}") from exc
    if len(encoded) > maximum:
        raise ValueError(f"persona 文件字段过长：{field}")
    return dict(value)


def _strings(value: object, field: str, *, maximum: int, item_maximum: int) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"persona 文件字段必须是数组：{field}")
    if len(value) > maximum:
        raise ValueError(f"persona 文件字段条目过多：{field}")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"persona 文件字段包含无效文本：{field}")
        text = item.strip()
        if len(text) > item_maximum:
            raise ValueError(f"persona 文件字段条目过长：{field}")
        out.append(text)
    return out


def normalize_persona_file(raw: object) -> dict[str, Any]:
    """Validate a persona file and return its normalized, immutable data.

    The public file uses ``persona`` for the core prompt text.  ``persona_text``
    is accepted as a compatibility alias for the early seed-pack draft.
    """
    if not isinstance(raw, dict):
        raise ValueError("persona 文件必须是 JSON 对象")
    allowed = {
        "id", "version", "name", "persona", "persona_text", "style",
        "boundaries", "example_dialogues", "license", "source",
        "content_rating", "locale",
    }
    unknown = set(raw) - allowed
    if unknown:
        raise ValueError(f"persona 文件包含未支持字段：{sorted(unknown)}")
    seed_id = _text(raw.get("id"), "id", maximum=64, required=True)
    if not _SEED_ID.fullmatch(seed_id):
        raise ValueError("persona 文件 id 只能使用小写字母、数字、点、下划线和短横线")
    version = _text(raw.get("version"), "version", maximum=32, required=True)
    name = _text(raw.get("name"), "name", maximum=80, required=True)
    persona = raw.get("persona")
    if persona is None:
        persona = raw.get("persona_text")
    text = _text(persona, "persona", maximum=_MAX_TEXT, required=True)
    style = _json_object(raw.get("style"), "style", maximum=_MAX_STYLE)
    boundaries = _strings(
        raw.get("boundaries"), "boundaries", maximum=_MAX_BOUNDARIES,
        item_maximum=_MAX_BOUNDARY,
    )
    examples = raw.get("example_dialogues")
    if examples is not None:
        if not isinstance(examples, (list, tuple)) or len(examples) > _MAX_EXAMPLES:
            raise ValueError("persona 文件 example_dialogues 必须是有限数组")
        for item in examples:
            if not isinstance(item, dict):
                raise ValueError("persona 文件 example_dialogues 条目必须是对象")
            if set(item) - {"user", "assistant"}:
                raise ValueError("persona 文件 example_dialogues 只允许 user/assistant")
            _text(item.get("user"), "example_dialogues.user", maximum=2000)
            _text(item.get("assistant"), "example_dialogues.assistant", maximum=2000)
    return {
        "id": seed_id,
        "version": version,
        "name": name,
        "persona": text,
        "style": style,
        "boundaries": boundaries,
        "example_dialogues": list(examples or []),
        "license": _text(raw.get("license"), "license", maximum=200),
        "source": _text(raw.get("source"), "source", maximum=200),
        "content_rating": _text(raw.get("content_rating"), "content_rating", maximum=32)
        or "general",
        "locale": _text(raw.get("locale"), "locale", maximum=20) or "zh-CN",
    }


def persona_payload_from_file(raw: object) -> dict[str, Any]:
    """Convert a validated persona file into the initial persona Artifact payload.

    The payload carries provenance for audit and rollback, but no evidence ids:
    seed content is authored configuration, not a fabricated chat event.
    """
    seed = normalize_persona_file(raw)
    return {
        "text": seed["persona"],
        "origin": PERSONA_ORIGIN_SEED,
        "seed_id": seed["id"],
        "seed_version": seed["version"],
        "seed_license": seed["license"],
        "seed_source": seed["source"],
        "persona_name": seed["name"],
        "style": seed["style"],
        "boundaries": seed["boundaries"],
        "content_rating": seed["content_rating"],
        "locale": seed["locale"],
    }


def compose_seed_evolution(base_text: str, behavior_text: str) -> str:
    """Append one deterministic Dream trait sentence to a seed base text."""
    base = str(base_text or "").strip()
    trait = str(behavior_text or "").strip()
    if not base:
        return trait
    if not trait:
        return base
    return f"{base}\n{trait}"


def seed_evolution_matches(text: object, base_text: object, behavior_text: str) -> bool:
    """Validate the deterministic text shape of a Dream revision over a seed."""
    if not isinstance(text, str) or not isinstance(base_text, str):
        return False
    return text == compose_seed_evolution(base_text, behavior_text)
