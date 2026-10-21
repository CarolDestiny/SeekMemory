"""Artifact 原语：统一头 + 按 family 区分的 payload。

本文件只定义数据结构，并提供构造（make）、修订（revise）、
校验（validate）与可读文本（content_of），不接触存储。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from .families import designated, example, media, memory, persona, secret

FAMILIES = ("memory", "example", "persona", "media", "secret", "designated")

_VALIDATORS = {
    "memory": memory.validate,
    "example": example.validate,
    "persona": persona.validate,
    "media": media.validate,
    "secret": secret.validate,
    "designated": designated.validate,
}

_TEXT_FIELDS = {
    "memory": "text",
    "persona": "text",
    "secret": "shadow_text",
    "designated": "text",
}

_SEQ = 0


@dataclass(frozen=True)
class Strength:
    weight: float = 1.0
    confidence: float = 1.0
    arousal: float = 0.3
    valence: float = 0.0
    funny: float = 0.0
    hits: int = 0


@dataclass(frozen=True)
class TimeSpan:
    created: str = ""
    updated: str = ""
    valid_from: str | None = None
    valid_to: str | None = None
    expires: str | None = None


@dataclass(frozen=True)
class Lineage:
    sources: tuple[str, ...] = ()
    derived_from: tuple[str, ...] = ()


@dataclass(frozen=True)
class Header:
    id: str
    family: str
    revision: int = 1
    state: str = "active"
    scope: str = "private"
    lineage: Lineage = field(default_factory=Lineage)
    strength: Strength = field(default_factory=Strength)
    time: TimeSpan = field(default_factory=TimeSpan)
    said_by: str = "owner"
    shareable: str = "private_only"
    subject_id: str = ""


@dataclass(frozen=True)
class Artifact:
    header: Header
    payload: dict[str, Any]


def _now() -> str:
    return datetime.now().isoformat(timespec="microseconds")


def _new_id() -> str:
    global _SEQ
    _SEQ += 1
    return "n_" + datetime.now().strftime("%Y%m%d%H%M%S%f") + f"{_SEQ:03d}"


def _coerce(kw: dict[str, Any]) -> dict[str, Any]:
    """把 dict 形式的嵌套头字段转成 dataclass，方便调用方。"""
    for key, cls in (("lineage", Lineage), ("strength", Strength), ("time", TimeSpan)):
        if isinstance(kw.get(key), dict):
            kw[key] = cls(**kw[key])
    return kw


def _stamp(time: TimeSpan) -> TimeSpan:
    now = _now()
    return replace(time, created=time.created or now, updated=time.updated or now)


def make(family: str, payload: dict[str, Any], **header_kw: Any) -> Artifact:
    """构造一条新 Artifact；family 必须合法，payload 原样保存。"""
    if family not in FAMILIES:
        raise ValueError(f"未知 family：{family!r}，可选：{', '.join(FAMILIES)}")
    kw = _coerce(dict(header_kw))
    kw.pop("family", None)
    kw.setdefault("id", _new_id())
    kw["time"] = _stamp(kw.get("time") or TimeSpan())
    return Artifact(header=Header(family=family, **kw), payload=dict(payload))


def revise(art: Artifact, payload: dict[str, Any] | None = None, **header_kw: Any) -> Artifact:
    """在保持 id 不变的前提下生成新版本，revision +1、updated 刷新。"""
    kw = _coerce(dict(header_kw))
    kw.pop("family", None)
    kw.pop("id", None)
    time = kw.pop("time", art.header.time)
    kw.setdefault("revision", art.header.revision + 1)
    kw["time"] = replace(time, updated=_now())
    new_payload = dict(art.payload if payload is None else payload)
    return Artifact(header=replace(art.header, **kw), payload=new_payload)


def validate(art: Artifact) -> None:
    """按 family 校验 payload 必填字段；不合法时抛中文 ValueError。"""
    family = art.header.family
    if family not in FAMILIES:
        raise ValueError(f"未知 family：{family!r}，可选：{', '.join(FAMILIES)}")
    if not isinstance(art.payload, dict):
        raise ValueError(f"{family} 的 payload 必须是 dict")
    _VALIDATORS[family](art.payload)


def _field(payload: dict[str, Any], key: str, family: str) -> str:
    if key not in payload:
        raise ValueError(f"{family} payload 缺少字段：{key}")
    value = payload[key]
    return "" if value is None else str(value)


def content_of(art: Artifact) -> str:
    """返回该 Artifact 的可读文本，供注入与去重使用。"""
    family, payload = art.header.family, art.payload
    if family == "example":
        user = _field(payload, "user", family)
        assistant = _field(payload, "assistant", family)
        return f"{user} → {assistant}"
    if family == "media":
        return str(payload.get("summary") or payload.get("title") or "")
    key = _TEXT_FIELDS.get(family)
    if key is None:
        raise ValueError(f"未知 family：{family!r}")
    return _field(payload, key, family)
