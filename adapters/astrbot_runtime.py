"""AstrBot event mapping for the host-agnostic AgentRuntime."""

from __future__ import annotations

try:
    from ..app.runtime.contracts import RuntimeInput, WakeDecision
except ImportError:
    from app.runtime.contracts import RuntimeInput, WakeDecision


class AstrBotRuntimeAdapter:
    """Translate AstrBot message events without importing AstrBot types."""

    @staticmethod
    def from_event(event, text: str, umo: str, sender: str,
                   unread_count: int = 0) -> RuntimeInput:
        try:
            private = bool(event.is_private_chat())
        except Exception:  # noqa: BLE001 - unknown host event defaults to group
            private = False
        value = str(text or "")
        return RuntimeInput(
            session_id=str(umo or ""),
            text=value,
            speaker_id=str(sender or ""),
            private=private,
            mentioned=private,
            question=("?" in value or "\uff1f" in value),
            unread_count=max(0, int(unread_count)),
        )

    @staticmethod
    def apply_decision(event, decision: WakeDecision) -> None:
        try:
            event.set_extra("_seekmemory_runtime_action", decision.action.value)
            event.set_extra("_seekmemory_runtime_reason", decision.reason)
        except Exception:  # noqa: BLE001 - observability must not break the host
            return
