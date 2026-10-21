from __future__ import annotations

from typing import Protocol

from core.artifact import Artifact
from core.source import Source
from core.versioning import StateEvent
from app.contracts import ChatRequest, ChatResponse


class ChatModel(Protocol):
    async def complete(self, request: ChatRequest) -> ChatResponse: ...


class SourceStore(Protocol):
    def append_sources(self, sources: list[Source]) -> int: ...


class ArtifactStore(Protocol):
    def commit(self, art: Artifact, *, expected_revision: int, op: str,
               reason: str = "", source_ids: tuple[str, ...] = ()) -> None: ...
    def get(self, node_id: str) -> Artifact | None: ...


class StateStore(Protocol):
    def append_state_event(self, event: StateEvent) -> None: ...
    def history(self, node_id: str) -> list[dict]: ...
