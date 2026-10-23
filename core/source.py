from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

ROLES = ("user", "assistant", "system", "tool", "external")


def content_hash(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def make_source_id(*, event_id: str = "", session_id: str, speaker_id: str,
                   role: str, text: str, at: str = "") -> str:
    if event_id:
        raw = "\x1f".join((event_id, session_id, speaker_id, role, text))
    else:
        raw = "\x1f".join((session_id, speaker_id, role, at, text))
    return "s_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True)
class Source:
    id: str
    turn_id: str
    session_id: str
    speaker_id: str
    role: str
    text: str
    at: str = ""
    reply_to: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.id:
            raise ValueError("source id missing")
        if self.role not in ROLES:
            raise ValueError(f"unknown source role: {self.role}")
        if not str(self.text or "").strip():
            raise ValueError("source text empty")

    @property
    def content_hash(self) -> str:
        return content_hash(self.text)
