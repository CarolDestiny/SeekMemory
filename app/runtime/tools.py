"""One tool policy with one enforced request-path filter.

AstrBot's ``on_using_llm_tool`` hook is observational; stopping it does not stop
the tool executor. The enforceable path is filtering ``req.func_tool`` in
``on_llm_request``. This module keeps the policy and the enforceable filter in
one object instead of maintaining an advisory policy plus a second guard type.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class ToolCall:
    """Metadata for one observed tool call."""

    name: str
    allowed: bool
    args_keys: tuple[str, ...] = ()
    enforced: bool = False

    @property
    def advisory(self) -> bool:
        return not self.enforced


@dataclass(frozen=True)
class ToolGuardDecision:
    """Decision returned by the pre-request tool filter."""

    tool_name: str
    allowed: bool
    enforced: bool = True
    reason: str = ""


class ToolPolicy:
    """Allowlist used for both request filtering and advisory traces."""

    def __init__(self, allowed_prefixes: tuple[str, ...] = ()) -> None:
        self.allowed_prefixes = tuple(str(x) for x in allowed_prefixes if x)

    def allows(self, name: str) -> bool:
        value = str(name or "")
        if not self.allowed_prefixes:
            return True
        return any(value.startswith(prefix) for prefix in self.allowed_prefixes)

    def check_tool(self, tool_name: str,
                   tool_args: Mapping[str, Any] | None = None) -> ToolGuardDecision:
        allowed = self.allows(tool_name)
        return ToolGuardDecision(
            tool_name=str(tool_name or ""),
            allowed=allowed,
            enforced=True,
            reason="allowed" if allowed else "policy_denied",
        )

    def filter_tool_set(self, tool_set: Any) -> tuple[str, ...]:
        """Remove denied tools from an AstrBot-like ToolSet.

        This is the real enforcement point: filtered tools never reach the model.
        The host object is duck-typed and failures are fail-open.
        """
        removed: list[str] = []
        remove_tool = getattr(tool_set, "remove_tool", None)
        if not callable(remove_tool):
            return ()
        tools = list(getattr(tool_set, "tools", ()) or ())
        for tool in tools:
            name = str(getattr(tool, "name", "") or "")
            if not name or self.allows(name):
                continue
            try:
                remove_tool(name)
                removed.append(name)
            except Exception:  # noqa: BLE001 - guard is fail-open
                continue
        return tuple(removed)

    def trace_call(self, tool_name: str, tool_args) -> ToolCall:
        """Classify one observed tool call without touching a host object."""
        name = str(tool_name or "")
        args = tool_args if isinstance(tool_args, dict) else {}
        return ToolCall(
            name=name,
            allowed=self.allows(name),
            args_keys=tuple(sorted(str(key) for key in args)),
            enforced=False,
        )


def tool_result_failed(tool_result: Any) -> bool:
    """Best-effort failure classification without persisting result content."""
    if tool_result is None:
        return False
    for attr in ("isError", "is_error"):
        try:
            if bool(getattr(tool_result, attr, False)):
                return True
        except Exception:  # noqa: BLE001 - metadata probe is fail-open
            pass
    try:
        status = str(getattr(tool_result, "status", "") or "").lower()
    except Exception:  # noqa: BLE001 - metadata probe is fail-open
        status = ""
    return status in {"error", "failed", "failure", "cancelled", "canceled"}


def trace_tool_call(tool_name: str, tool_args, policy: ToolPolicy) -> ToolCall:
    """Compatibility helper for the old function-style call site."""
    return policy.trace_call(tool_name, tool_args)
