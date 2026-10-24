"""AstrBot event mapping for the host-agnostic AgentRuntime."""

from __future__ import annotations

try:
    from ..app.runtime.contracts import RuntimeInput, WakeAction, RunDecision
    from ..app.runtime.tools import ToolPolicy, trace_tool_call
except ImportError:
    from app.runtime.contracts import RuntimeInput, WakeAction, RunDecision
    from app.runtime.tools import ToolPolicy, trace_tool_call


class AstrBotRuntimeAdapter:
    """Translate AstrBot message events without importing AstrBot types."""

    @staticmethod
    def from_event(event, text: str, umo: str, sender: str,
                   unread_count: int = 0, unread_seq: int = 0) -> RuntimeInput:
        try:
            private = bool(event.is_private_chat())
        except Exception:  # noqa: BLE001 - unknown host event defaults to group
            private = False
        value = str(text or "")
        try:
            created_at = float(getattr(event, "created_at", 0.0) or 0.0)
        except (TypeError, ValueError):
            created_at = 0.0
        direct = bool(getattr(event, "is_at_or_wake_command", False))
        return RuntimeInput(
            session_id=str(umo or ""),
            text=value,
            speaker_id=str(sender or ""),
            private=private,
            mentioned=private or direct,
            question=("?" in value or "\uff1f" in value),
            unread_count=max(0, int(unread_count)),
            unread_seq=max(0, int(unread_seq)),
            at=created_at,
        )

    @staticmethod
    def apply_decision(event, decision: RunDecision) -> None:
        try:
            event.set_extra("_seekmemory_runtime_action", decision.action.value)
            event.set_extra("_seekmemory_runtime_reason", decision.reason)
        except Exception:  # noqa: BLE001 - observability must not break the host
            return

    @staticmethod
    def apply_llm_gate(event, decision: RunDecision, enabled: bool) -> None:
        if not enabled:
            return
        try:
            event.should_call_llm(
                decision.must_reply or decision.action is WakeAction.REPLY
            )
        except Exception:  # noqa: BLE001 - host version may not expose the gate
            return

    @staticmethod
    def observe_tool(event, tool, tool_args, policy: ToolPolicy):
        name = str(getattr(tool, "name", tool) or "")
        return trace_tool_call(event, name, tool_args, policy)
