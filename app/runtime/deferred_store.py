"""Protected, temporary delivery outbox; traces and session state stay body-free."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class DeferredReply:
    run_id: str
    session_id: str
    text: str
    speaker_id: str
    user_source_id: str
    read_through_seq: int
    at: str
    recall_ids: tuple[str, ...] = ()
    designated_ids: tuple[str, ...] = ()
    status: str = "sending"
    designated_revisions: dict[str, int] = field(default_factory=dict)
    sent_at: float = 0.0


class DeferredStore(Protocol):
    def get(self, session_id: str) -> DeferredReply | None: ...
    def put(self, reply: DeferredReply) -> None: ...
    def remove(self, run_id: str) -> None: ...
    def sent(self) -> tuple[DeferredReply, ...]: ...


class InMemoryDeferredStore:
    """Ephemeral outbox for non-persistent runtime hosts."""

    def __init__(self) -> None:
        self.items: dict[str, DeferredReply] = {}

    def get(self, session_id: str) -> DeferredReply | None:
        return self.items.get(session_id)

    def put(self, reply: DeferredReply) -> None:
        self.items[reply.session_id] = reply

    def remove(self, run_id: str) -> None:
        self.items = {sid: row for sid, row in self.items.items() if row.run_id != run_id}

    def sent(self) -> tuple[DeferredReply, ...]:
        return tuple(row for row in self.items.values() if row.status == "sent")


class DBDeferredStore:
    """Persist outbox through the SQLite facade, propagating write failures."""

    def __init__(self, db: Any) -> None:
        self.db = db

    @staticmethod
    def _reply(raw: dict[str, Any]) -> DeferredReply:
        data = dict(raw)
        data["recall_ids"] = tuple(data.get("recall_ids") or ())
        data["designated_ids"] = tuple(data.get("designated_ids") or ())
        return DeferredReply(**data)

    def get(self, session_id: str) -> DeferredReply | None:
        raw = self.db.get_deferred_reply(session_id)
        return self._reply(raw) if raw else None

    def put(self, reply: DeferredReply) -> None:
        self.db.put_deferred_reply(asdict(reply))

    def remove(self, run_id: str) -> None:
        self.db.remove_deferred_reply(run_id)

    def sent(self) -> tuple[DeferredReply, ...]:
        return tuple(self._reply(raw) for raw in self.db.sent_deferred_replies())
