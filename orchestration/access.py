"""Pure conversation permission policy."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AccessPolicy:
    """Decide whether one session may be observed or recalled.

    The policy has no host dependencies. Callers reduce a host event to the
    session id and sender id before asking for a decision.
    """

    mode: str = "owner_only"
    owner_umo: str = ""
    trusted_ids: frozenset[str] = frozenset()
    observe_groups: bool = True

    @staticmethod
    def is_group(session_id: str) -> bool:
        return ":GroupMessage:" in str(session_id or "")

    def may_remember(self, session_id: str, sender_id: str) -> bool:
        session = str(session_id or "")
        sender = str(sender_id or "")
        if self.mode == "everyone":
            return True
        if session and session == self.owner_umo:
            return True
        if self.mode == "owner_and_trusted":
            return sender in self.trusted_ids or session == self.owner_umo
        return False

    def may_observe(self, session_id: str, sender_id: str) -> bool:
        if self.may_remember(session_id, sender_id):
            return True
        return bool(self.observe_groups) and self.is_group(session_id)

    def may_recall(self, session_id: str, sender_id: str) -> bool:
        return self.may_observe(session_id, sender_id)
