"""Tool policy and tool-call trace contracts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolCall:
    name: str
    allowed: bool
    args_keys: tuple[str, ...] = ()


class ToolPolicy:
    """Advisory allowlist; host enforcement remains in the adapter."""

    def __init__(self, allowed_prefixes: tuple[str, ...] = ()) -> None:
        self.allowed_prefixes = tuple(str(x) for x in allowed_prefixes if x)

    def allows(self, name: str) -> bool:
        value = str(name or "")
        if not self.allowed_prefixes:
            return True
        return any(value.startswith(prefix) for prefix in self.allowed_prefixes)


def trace_tool_call(event, tool_name: str, tool_args, policy: ToolPolicy) -> ToolCall:
    """Record a tool call on the host event without executing or denying it."""
    name = str(tool_name or "")
    args = tool_args if isinstance(tool_args, dict) else {}
    call = ToolCall(name=name, allowed=policy.allows(name),
                    args_keys=tuple(sorted(str(key) for key in args)))
    try:
        existing = event.get_extra("_seekmemory_tool_calls", ()) or ()
        event.set_extra("_seekmemory_tool_calls", tuple(existing) + (name,))
        event.set_extra("_seekmemory_tool_allowed", call.allowed)
    except Exception:  # noqa: BLE001 - trace must not break host
        pass
    return call
