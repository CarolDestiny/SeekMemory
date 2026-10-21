from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .artifact import Artifact

OPS = ("create", "revise", "reinforce", "deliver", "merge", "forget", "promote")
CHECKPOINT_OPS = ("reinforce", "deliver", "promote")


class VersionError(ValueError):
    pass


@dataclass(frozen=True)
class StateEvent:
    id: str
    entity_id: str
    revision_seen: int
    op: str
    delta: dict[str, Any] = field(default_factory=dict)
    at: str = ""

    def validate(self) -> None:
        if not self.id or not self.entity_id:
            raise ValueError("state event needs id and entity_id")
        if self.revision_seen < 1:
            raise ValueError("revision_seen must be >= 1")
        if not isinstance(self.delta, dict):
            raise ValueError("delta must be a dict")


def assert_next_revision(previous: Artifact | None, current: Artifact) -> None:
    if current.header.revision < 1:
        raise VersionError("revision must start at 1")
    if previous is None:
        if current.header.revision != 1:
            raise VersionError("new artifact revision must be 1")
        return
    if current.header.id != previous.header.id:
        raise VersionError("artifact id changed")
    if current.header.family != previous.header.family:
        raise VersionError("artifact family changed")
    wanted = previous.header.revision + 1
    if current.header.revision != wanted:
        raise VersionError(f"expected revision {wanted}, got {current.header.revision}")
    if current.header.time.created != previous.header.time.created:
        raise VersionError("created timestamp changed")


def is_semantic_change(previous: Artifact | None, current: Artifact) -> bool:
    if previous is None:
        return True
    if previous.payload != current.payload:
        return True
    names = ("family", "state", "scope", "subject_id", "shareable")
    return any(getattr(previous.header, n) != getattr(current.header, n) for n in names)
