"""Tool policy and tool-call trace contracts.

AstrBot's ``on_using_llm_tool`` hook is observational for the pipelined tool
executor. The hook return value is ignored and stopping the event only stops
further hooks; the tool-loop runner still calls ``tool_executor.execute()``.
Consequently a plugin cannot veto a tool from that hook in the inspected host
version. ``ToolPolicy`` is therefore explicitly advisory. ``ToolGuard`` and
``EnforcedToolPolicy`` describe the contract a future host must satisfy before
an adapter may report enforcement.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, runtime_checkable


@dataclass(frozen=True)
class ToolCall:
    """Metadata for one observed tool call.

    ``allowed`` is only the advisory policy verdict. It does not mean the host
    permitted execution. Use ``enforced`` to distinguish a real pre-dispatch
    veto from this observation-only path.
    """

    name: str
    allowed: bool
    args_keys: tuple[str, ...] = ()
    enforced: bool = False

    @property
    def policy_match(self) -> bool:
        """Alias that makes the advisory meaning of ``allowed`` explicit."""

        return self.allowed

    @property
    def advisory(self) -> bool:
        return not self.enforced


@dataclass(frozen=True)
class ToolGuardDecision:
    """Decision returned by a host-integrated tool guard."""

    tool_name: str
    allowed: bool
    enforced: bool
    reason: str = ""


@runtime_checkable
class ToolGuard(Protocol):
    """Contract for a guard consulted before a tool is dispatched.

    A host implementation must call :meth:`check_tool` before executing a tool
    and must not execute when the returned decision has ``allowed=False`` and
    ``enforced=True``. This repository does not wire this contract into AstrBot
    because the inspected ``on_using_llm_tool`` path cannot stop execution.
    """

    def check_tool(
        self, tool_name: str, tool_args: Mapping[str, Any]
    ) -> ToolGuardDecision: ...


@runtime_checkable
class EnforcedToolPolicy(ToolGuard, Protocol):
    """Marker contract for a tool policy that the host can truly enforce.

    Do not adapt :class:`ToolPolicy` to this protocol. It is deliberately kept
    separate so callers can tell an advisory allowlist from a pre-dispatch veto.
    """


class ToolPolicy:
    """Advisory allowlist for observed tool calls.

    The current AstrBot adapter cannot block a tool from ``on_using_llm_tool``.
    A policy mismatch is recorded for observability only.
    """

    enforced = False
    advisory = True

    def __init__(self, allowed_prefixes: tuple[str, ...] = ()) -> None:
        self.allowed_prefixes = tuple(str(x) for x in allowed_prefixes if x)

    def allows(self, name: str) -> bool:
        value = str(name or "")
        if not self.allowed_prefixes:
            return True
        return any(value.startswith(prefix) for prefix in self.allowed_prefixes)


def tool_result_failed(tool_result: Any) -> bool:
    """Best-effort failure classification for AstrBot/MCP tool results.

    Only status metadata is inspected; tool arguments and result content are
    never persisted by this helper.
    """

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


def trace_tool_call(event, tool_name: str, tool_args, policy: ToolPolicy) -> ToolCall:
    """Record advisory policy metadata on the host event.

    This function never executes or denies a tool. The returned ``enforced``
    flag is always false because the inspected host hook cannot veto execution.
    """

    name = str(tool_name or "")
    args = tool_args if isinstance(tool_args, dict) else {}
    call = ToolCall(
        name=name,
        allowed=policy.allows(name),
        args_keys=tuple(sorted(str(key) for key in args)),
        enforced=False,
    )
    try:
        existing = event.get_extra("_seekmemory_tool_calls", ()) or ()
        event.set_extra("_seekmemory_tool_calls", tuple(existing) + (name,))
        mismatches = event.get_extra("_seekmemory_tool_policy_mismatches", ()) or ()
        if not call.allowed:
            event.set_extra(
                "_seekmemory_tool_policy_mismatches", tuple(mismatches) + (name,)
            )
        event.set_extra("_seekmemory_tool_policy_enforced", False)
    except Exception:  # noqa: BLE001 - trace must not break host
        pass
    return call


class PolicyToolGuard:
    """A coarse pre-dispatch guard that can filter a host ToolSet.

    AstrBot cannot veto from ``on_using_llm_tool``, but its ``on_llm_request``
    hook exposes ``req.func_tool``. Removing a denied tool there means the model
    never sees or calls it. This class implements that enforceable path and is
    intentionally separate from the advisory ``ToolPolicy`` trace.
    """

    def __init__(self, policy: ToolPolicy) -> None:
        self.policy = policy

    def check_tool(self, tool_name: str, tool_args: Mapping[str, Any]) -> ToolGuardDecision:
        allowed = self.policy.allows(tool_name)
        return ToolGuardDecision(
            tool_name=str(tool_name or ""),
            allowed=allowed,
            enforced=True,
            reason="allowed" if allowed else "policy_denied",
        )

    def filter_tool_set(self, tool_set: Any) -> tuple[str, ...]:
        """Remove denied tools from an AstrBot-like ToolSet.

        The host object is duck-typed: it must expose ``tools`` and
        ``remove_tool(name)``. No tool is executed here.
        """
        removed: list[str] = []
        tools = list(getattr(tool_set, "tools", ()) or ())
        for tool in tools:
            name = str(getattr(tool, "name", "") or "")
            if name and not self.policy.allows(name):
                tool_set.remove_tool(name)
                removed.append(name)
        return tuple(removed)
