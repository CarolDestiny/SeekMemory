"""Single write-back service for completed runtime runs."""

from __future__ import annotations

import datetime
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Protocol
from uuid import uuid4

try:
    from ...core.source import Source, make_source_id
except ImportError:  # top-level package import in scripts/tests
    from core.source import Source, make_source_id
from .episode import EpisodeRecord, normalize_tool_calls, safe_error_code
from ..delivery import confirm_designated_delivery


class SourceSink(Protocol):
    def append_sources(self, sources: list[Source]) -> int: ...


class PendingSink(Protocol):
    def add(self, umo: str, text: str, sender: str = "", source_id: str = "",
            at: str = "", *, source: Source | None = None, turn_id: str = "",
            reply_to: str = "", deferred: bool = False,
            role: str = "user") -> Any: ...


class CheckpointSink(Protocol):
    def record(self, art: Any, at: str = "") -> bool: ...


class EpisodeWriter(Protocol):
    def record(self, episode: EpisodeRecord) -> bool: ...
    def completed(self, run_id: str) -> bool: ...


@dataclass(frozen=True)
class RecordedReply:
    run_id: str
    session_id: str
    turn_id: str
    assistant_source_id: str
    response_chars: int
    recall_ids: tuple[str, ...] = ()
    designated_ids: tuple[str, ...] = ()
    designated_revisions: Mapping[str, int] | None = None


class RunRecorder:
    """Owns assistant Source, pending buffer and episode write-back.

    A run id is the idempotency boundary. Source ids are deterministic and the
    database uses INSERT OR IGNORE, while repeated calls in one process are
    short-circuited here so checkpoints and episode rows are not duplicated.
    """

    def __init__(
        self,
        *,
        db: SourceSink | None,
        buffer: PendingSink | None,
        checkpoint: CheckpointSink | None,
        episodes: EpisodeWriter | None,
        cache: Any | None = None,
        clock=None,
        max_records: int = 1024,
    ) -> None:
        self.db = db
        self.buffer = buffer
        self.checkpoint = checkpoint
        self.episodes = episodes
        self.cache = cache
        self.clock = clock or (lambda: datetime.datetime.now().isoformat(timespec="seconds"))
        self.max_records = max(1, int(max_records))
        self._replies: OrderedDict[str, RecordedReply] = OrderedDict()
        self._episodes: OrderedDict[str, bool] = OrderedDict()
        self._reinforced: OrderedDict[str, set[str]] = OrderedDict()

    def _remember(self, records: OrderedDict, key: str, value: Any) -> None:
        records[key] = value
        records.move_to_end(key)
        while len(records) > max(1, self.max_records):
            records.popitem(last=False)

    def _delivery_completed(self, key: str) -> bool:
        if self._episodes.get(key):
            return True
        completed = getattr(self.episodes, "completed", None)
        if completed is not None and completed(key):
            self._remember(self._episodes, key, True)
            return True
        return False

    @staticmethod
    def new_run_id() -> str:
        return uuid4().hex

    def record_reply(
        self,
        *,
        run_id: str,
        session_id: str,
        text: str,
        speaker_id: str,
        turn_id: str = "",
        reply_to: str = "",
        at: str = "",
        recall_ids: Iterable[str] = (),
        designated_ids: Iterable[str] = (),
        designated_revisions: Mapping[str, int] | None = None,
        source_suffix: str = "assistant",
    ) -> RecordedReply:
        """Write one assistant Source and its pending projection exactly once."""
        key = str(run_id or "").strip() or self.new_run_id()
        existing = self._replies.get(key)
        if existing is not None:
            return existing

        clean = str(text or "").strip()
        if not clean:
            raise ValueError("assistant reply text is empty")
        session = str(session_id or "")
        speaker = str(speaker_id or "")
        moment = str(at or self.clock())
        turn = str(turn_id or "").strip() or f"run:{key}"
        source_id = make_source_id(
            event_id=f"{turn}:{source_suffix or 'assistant'}",
            session_id=session,
            speaker_id=speaker,
            role="assistant",
            text=clean,
        )
        source = Source(
            source_id,
            turn,
            session,
            speaker,
            "assistant",
            clean,
            moment,
            reply_to=str(reply_to or "") or None,
        )
        completed = self._delivery_completed(key)
        if self.db is not None and not completed:
            self.db.append_sources([source])
        if self.buffer is not None and not completed:
            self.buffer.add(
                session,
                clean,
                speaker,
                source_id,
                moment,
                source=source,
                turn_id=turn,
                role="assistant",
            )
        result = RecordedReply(
            key, session, turn, source_id, len(clean),
            tuple(dict.fromkeys(recall_ids or ())),
            tuple(dict.fromkeys(designated_ids or ())),
            dict(designated_revisions) if designated_revisions is not None else None,
        )
        self._remember(self._replies, key, result)
        return result

    def record_delivery(
        self,
        *,
        run_id: str,
        session_id: str,
        decision: str,
        reason: str,
        action: str = "reply",
        response_chars: int = 0,
        tool_calls: Iterable[Any] | None = (),
        user_source_id: str = "",
        assistant_source_id: str = "",
        at: str = "",
        recall_ids: Iterable[str] = (),
        designated_ids: Iterable[str] = (),
        designated_revisions: Mapping[str, int] | None = None,
    ) -> bool:
        """Confirm delivery effects; failed writes remain retryable."""
        key = str(run_id or "").strip() or self.new_run_id()
        if self._delivery_completed(key):
            return True
        staged = self._replies.get(key)
        retained = tuple(dict.fromkeys(
            (*getattr(staged, "recall_ids", ()), *(recall_ids or ()))
        ))
        designated = tuple(dict.fromkeys(
            (*getattr(staged, "designated_ids", ()), *(designated_ids or ()))
        ))
        moment = str(at or self.clock())
        revisions = (
            designated_revisions if designated_revisions is not None
            else getattr(staged, "designated_revisions", None)
        )
        if designated:
            confirm_designated_delivery(
                self.db, self.cache, designated, at=moment,
                expected_revisions=revisions,
            )
        self._reinforce_recall(key, retained, moment)
        self._record_episode(
            run_id=key,
            session_id=session_id,
            decision=decision,
            reason=reason,
            action=action,
            delivered=True,
            response_chars=response_chars,
            tool_calls=tool_calls,
            outcome="ok",
            user_source_id=user_source_id,
            assistant_source_id=assistant_source_id,
            at=moment,
        )
        self._remember(self._episodes, key, True)
        self._reinforced.pop(key, None)
        return True

    def record_error(
        self,
        *,
        run_id: str,
        session_id: str,
        decision: str,
        reason: str,
        action: str = "reply",
        error: Any = "",
        user_source_id: str = "",
        assistant_source_id: str = "",
        at: str = "",
    ) -> None:
        """Record one failed run without message bodies or exception text."""
        self._record_episode(
            run_id=run_id,
            session_id=session_id,
            decision=decision,
            reason=reason,
            action=action,
            delivered=False,
            error=safe_error_code(error) or "error",
            outcome="error",
            user_source_id=user_source_id,
            assistant_source_id=assistant_source_id,
            at=at,
        )

    def record_deferred_reply(
        self,
        *,
        run_id: str,
        session_id: str,
        text: str,
        speaker_id: str,
        user_source_id: str,
        decision: str = "wait",
        reason: str = "deferred_wait",
        at: str = "",
        recall_ids: Iterable[str] = (),
        designated_ids: Iterable[str] = (),
        designated_revisions: Mapping[str, int] | None = None,
    ) -> RecordedReply:
        """Persist a deferred assistant reply and its delivered episode."""
        reply = self.record_reply(
            run_id=run_id,
            session_id=session_id,
            text=text,
            speaker_id=speaker_id,
            turn_id=user_source_id,
            reply_to=user_source_id,
            at=at,
            source_suffix="deferred",
            recall_ids=recall_ids,
            designated_ids=designated_ids,
            designated_revisions=designated_revisions,
        )
        self.record_delivery(
            run_id=run_id,
            session_id=session_id,
            decision=decision,
            reason=reason,
            action="reply",
            response_chars=reply.response_chars,
            user_source_id=user_source_id,
            assistant_source_id=reply.assistant_source_id,
            at=at,
            recall_ids=recall_ids,
            designated_ids=designated_ids,
            designated_revisions=designated_revisions,
        )
        return reply

    def record_deferred_error(
        self,
        *,
        run_id: str,
        session_id: str,
        user_source_id: str,
        error: Any,
        decision: str = "wait",
        reason: str = "deferred_wait",
        at: str = "",
    ) -> None:
        self.record_error(
            run_id=run_id,
            session_id=session_id,
            decision=decision,
            reason=reason,
            action="reply",
            error=error,
            user_source_id=user_source_id,
            at=at,
        )

    def _reinforce_recall(self, run_id: str, recall_ids: Iterable[str], at: str) -> None:
        if self.checkpoint is None:
            return
        completed = self._reinforced.get(run_id)
        if completed is None:
            completed = set()
            self._remember(self._reinforced, run_id, completed)
        for art_id in recall_ids or ():
            if art_id in completed:
                continue
            art = self.cache.get(str(art_id)) if self.cache is not None else None
            if art is not None and getattr(art.header, "family", "") == "memory":
                self.checkpoint.record(art, at=at)
            completed.add(art_id)

    def _record_episode(
        self,
        *,
        run_id: str,
        session_id: str,
        decision: str,
        reason: str,
        action: str,
        delivered: bool,
        response_chars: int = 0,
        tool_calls: Iterable[Any] | None = (),
        outcome: str = "",
        error: str = "",
        user_source_id: str = "",
        assistant_source_id: str = "",
        at: str = "",
    ) -> None:
        key = str(run_id or "").strip()
        if key and key in self._episodes:
            return
        if self.episodes is None:
            return
        persisted = self.episodes.record(EpisodeRecord(
            session_id=str(session_id or ""),
            at=str(at or self.clock()),
            decision=str(decision or ""),
            reason=str(reason or ""),
            action=str(action or ""),
            delivered=bool(delivered),
            response_chars=max(0, int(response_chars or 0)),
            tool_calls=normalize_tool_calls(tool_calls),
            outcome=str(outcome or ""),
            error=str(error or ""),
            user_source_id=str(user_source_id or ""),
            assistant_source_id=str(assistant_source_id or ""),
            run_id=key,
        ))
        if persisted is False:
            raise RuntimeError("episode_write_failed")
        if key:
            self._remember(self._episodes, key, bool(delivered))
