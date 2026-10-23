"""AstrBot event mapping for the host-agnostic AgentRuntime."""

from __future__ import annotations

try:
    from ..app.runtime.contracts import RuntimeInput, WakeAction, WakeDecision
    from ..app.runtime.tools import ToolPolicy, trace_tool_call
except ImportError:
    from app.runtime.contracts import RuntimeInput, WakeAction, WakeDecision
    from app.runtime.tools import ToolPolicy, trace_tool_call


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

    @staticmethod
    def apply_llm_gate(event, decision: WakeDecision, enabled: bool) -> None:
        if not enabled:
            return
        try:
            event.should_call_llm(decision.action in (WakeAction.REPLY, WakeAction.PROACTIVE))
        except Exception:  # noqa: BLE001 - host version may not expose the gate
            return

    @staticmethod
    def observe_tool(event, tool, tool_args, policy: ToolPolicy):
        name = str(getattr(tool, "name", tool) or "")
        return trace_tool_call(event, name, tool_args, policy)
