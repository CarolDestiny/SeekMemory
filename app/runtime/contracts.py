"""Host-agnostic contracts for the SeekMemory agent runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol


class WakeAction(str, Enum):
    IGNORE = "ignore"
    OBSERVE = "observe"
    WAIT = "wait"
    REPLY = "reply"
    PROACTIVE = "proactive"
    SLEEP = "sleep"


@dataclass(frozen=True)
class RuntimeInput:
    """One inbound event reduced to fields the runtime can reason about."""

    session_id: str
    text: str
    speaker_id: str = ""
    private: bool = True
    mentioned: bool = False
    name_mentioned: bool = False
    question: bool = False
    reply_to_bot: bool = False
    keyword_hit: bool = False
    unread_count: int = 0
    at: float = 0.0


@dataclass
class SocialState:
    """Per-session timing and attention state. This is not memory."""

    session_id: str
    last_seen_at: float = 0.0
    last_spoke_at: float = 0.0
    last_wake_at: float = 0.0
    quiet_until: float = 0.0
    unread_count: int = 0
    reply_count: int = 0
    ignored_streak: int = 0
    last_action: str = ""
    last_reason: str = ""
    reply_cooldown_seconds: float = 30.0
    proactive_idle_seconds: float = 1800.0
    proactive_probability: float = 0.1


@dataclass(frozen=True)
class WakeDecision:
    action: WakeAction
    reason: str
    wait_seconds: float = 0.0
    confidence: float = 1.0


@dataclass(frozen=True)
class RuntimeResult:
    delivered: bool = False
    response_text: str = ""
    tool_calls: tuple[str, ...] = ()
    error: str = ""


class StateStore(Protocol):
    def get(self, session_id: str) -> SocialState: ...
    def put(self, state: SocialState) -> None: ...


class TraceSink(Protocol):
    def record(self, kind: str, status: str, context: dict[str, Any] | None = None) -> None: ...


class MemoryContextPort(Protocol):
    def build_context(self, event: RuntimeInput) -> str: ...


class ActionPort(Protocol):
    async def send(self, session_id: str, text: str) -> None: ...
    async def wait(self, seconds: float) -> None: ...
    async def proactive(self, session_id: str, text: str) -> None: ...
