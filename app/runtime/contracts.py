"""Host-agnostic contracts for the SeekMemory agent runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol


class AttentionLevel(str, Enum):
    AMBIENT = "ambient"
    ADDRESSED = "addressed"
    DIRECT = "direct"
    PRIVATE = "private"


class WakeAction(str, Enum):
    IGNORE = "ignore"
    OBSERVE = "observe"
    WAIT = "wait"
    REPLY = "reply"


@dataclass(frozen=True)
class RuntimeInput:
    """One inbound event reduced to fields the runtime can reason about."""

    session_id: str
    text: str
    speaker_id: str = ""
    private: bool = False
    mentioned: bool = False
    question: bool = False
    unread_count: int = 0
    unread_seq: int = 0
    at: float = 0.0


@dataclass(frozen=True)
class RunContext:
    """One inbound runtime unit before it becomes a durable result."""

    session_id: str
    text: str
    source_id: str = ""
    bot_id: str = ""
    at: float = 0.0
    run_id: str = ""


@dataclass(frozen=True)
class RunResult:
    """Observed outcome of one deferred runtime run."""

    run_id: str
    session_id: str
    delivered: bool
    assistant_source_id: str = ""
    response_chars: int = 0
    error: str = ""


@dataclass
class SessionState:
    """Per-session timing and attention state. This is not memory."""

    session_id: str
    last_seen_at: float = 0.0
    last_spoke_at: float = 0.0
    quiet_until: float = 0.0
    wait_until: float = 0.0
    cooldown_until: float = 0.0
    unread_count: int = 0
    last_unread_seq: int = 0
    read_through_seq: int = 0
    ignored_streak: int = 0
    dispatch_attempts: int = 0
    next_retry_at: float = 0.0
    last_dispatched_source_id: str = ""
    last_action: str = ""
    last_reason: str = ""
    reply_cooldown_seconds: float = 30.0


@dataclass(frozen=True)
class RunDecision:
    action: WakeAction
    reason: str
    attention: AttentionLevel = AttentionLevel.AMBIENT
    must_reply: bool = False


class StateStore(Protocol):
    def get(self, session_id: str) -> SessionState: ...
    def put(self, state: SessionState) -> None: ...


class TraceSink(Protocol):
    def record(self, kind: str, status: str, context: dict[str, Any] | None = None) -> None: ...


@dataclass(frozen=True)
class MemoryContext:
    text: str = ""
    info: dict[str, Any] = field(default_factory=dict)


class MemoryContextPort(Protocol):
    def build_context(self, event: RuntimeInput) -> MemoryContext: ...


class ModelGateway(Protocol):
    async def complete(
        self, session_id: str, prompt: str, system_prompt: str | None = None
    ) -> str: ...


class MessageSender(Protocol):
    async def send(self, session_id: str, text: str) -> bool: ...
