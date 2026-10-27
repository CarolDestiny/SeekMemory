"""One UTC+8 time hook at AstrBot's write and read boundaries."""

from __future__ import annotations

import datetime
import time
from dataclasses import replace
from typing import Any

try:
    from ..app.contracts import DialogueTurn
    from ..app.ports import SourceStore
    from ..app.runtime.recorder import RecordedReply, RecordedTurn, RunRecorder
    from ..core.source import Source
    from ..perceive.buffer import Buffer
except ImportError:  # standalone adapter imports in scripts/tests
    from app.contracts import DialogueTurn
    from app.ports import SourceStore
    from app.runtime.recorder import RecordedReply, RecordedTurn, RunRecorder
    from core.source import Source
    from perceive.buffer import Buffer

UTC8 = datetime.timezone(datetime.timedelta(hours=8))


def utc8_time_hook(at: str = "", *, now: bool = False, projection: bool = False) -> str:
    """Convert known instants; preserve legacy values with no timezone.

    New writes keep the UTC+8 offset. Kernel views keep their existing naive
    ISO shape. Empty historical values stay empty; only a write asks for now.
    """
    if not at:
        if not now:
            return at
        value = datetime.datetime.now(UTC8)
    else:
        try:
            value = datetime.datetime.fromisoformat(at)
        except (TypeError, ValueError):
            return at
        if value.tzinfo is None:
            return at
    value = value.astimezone(UTC8)
    if projection:
        value = value.replace(tzinfo=None)
    return value.isoformat(timespec="seconds")


def utc8_timestamp(at: str) -> float:
    """Return a known instant, or zero when the legacy timezone is unknown."""
    try:
        value = datetime.datetime.fromisoformat(utc8_time_hook(at))
        return value.timestamp() if value.tzinfo is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


class AstrBotSourceView:
    """Normalize extraction's evidence read view without rewriting Sources."""

    def __init__(self, sources: SourceStore) -> None:
        self.sources = sources

    def append_sources(self, sources: list[Source]) -> int:
        return self.sources.append_sources(sources)

    def recent_sources(self, *, since: str, limit: int) -> list[Source]:
        return [
            replace(source, at=utc8_time_hook(source.at, projection=True))
            for source in self.sources.recent_sources(since=since, limit=limit)
        ]

    def source_umo(self, source_id: str) -> str:
        return self.sources.source_umo(source_id)

    def source_umos(self, source_ids: list[str]) -> dict[str, str]:
        return self.sources.source_umos(source_ids)

    def sources_by_ids(self, source_ids: list[str]) -> dict[str, Source]:
        return {
            key: replace(source, at=utc8_time_hook(source.at, projection=True))
            for key, source in self.sources.sources_by_ids(source_ids).items()
        }


class AstrBotRunRecorder(RunRecorder):
    """Normalize at the host boundary, then reuse every existing write path."""

    def record_user(self, *, at: str = "", **fields: Any) -> RecordedTurn:
        return super().record_user(at=utc8_time_hook(at, now=True), **fields)

    def record_reply(self, *, at: str = "", **fields: Any) -> RecordedReply:
        return super().record_reply(at=utc8_time_hook(at, now=True), **fields)

    def record_delivery(self, *, at: str = "", **fields: Any) -> None:
        super().record_delivery(at=utc8_time_hook(at, now=True), **fields)

    def record_error(self, *, at: str = "", **fields: Any) -> None:
        super().record_error(at=utc8_time_hook(at, now=True), **fields)


class AstrBotBuffer(Buffer):
    """Use UTC+8 views and age signals without changing the kernel Buffer."""

    def __init__(self, path: str = "", extraction=None) -> None:
        self._source_times: dict[str, float] = {}
        super().__init__(path, extraction=extraction)

    @staticmethod
    def _view(turn: DialogueTurn) -> DialogueTurn:
        return replace(turn, at=utc8_time_hook(turn.at, projection=True))

    def add(
        self, umo: str, text: str, sender: str = "", source_id: str = "",
        at: str = "", *, source: Source | None = None, **fields: Any,
    ) -> DialogueTurn | None:
        at = utc8_time_hook(at or (source.at if source is not None else ""), now=True)
        turn = super().add(
            umo, text, sender, source_id, at,
            source=source, **fields,
        )
        if turn is not None:
            stamp = utc8_timestamp(at)
            if stamp and turn.source_id:
                self._source_times[turn.source_id] = stamp
            self.items = [self._view(item) for item in self.items]
            self._timestamps()
            return self._view(turn)
        return None

    def _topic_for(
        self, turn: DialogueTurn, previous: DialogueTurn | None,
        parent: DialogueTurn | None = None,
    ) -> str:
        return super()._topic_for(
            self._view(turn),
            self._view(previous) if previous is not None else None,
            self._view(parent) if parent is not None else None,
        )

    def _load_projection(self) -> None:
        super()._load_projection()
        self._source_times = {
            turn.source_id: utc8_timestamp(turn.at) for turn in self.items
            if turn.source_id
        }
        self.items = [self._view(turn) for turn in self.items]
        self.last_ts = max(self._timestamps(), default=0.0)

    def _timestamps(self) -> list[float]:
        pending_ids = {turn.source_id for turn in self.items}
        self._source_times = {
            key: stamp for key, stamp in self._source_times.items() if key in pending_ids
        }
        return [stamp for stamp in self._source_times.values() if stamp]

    def oldest_topic_age(self) -> float:
        stamps = self._timestamps()
        return max(0.0, time.time() - min(stamps)) if stamps else 0.0
