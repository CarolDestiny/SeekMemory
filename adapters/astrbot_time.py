"""UTC+8 timestamp policy at the AstrBot write and buffer boundaries."""

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


def utc8_time(at: str = "") -> str:
    """Keep the kernel's naive ISO shape, interpreting host timestamps in UTC+8."""
    if not at:
        value = datetime.datetime.now(UTC8)
    else:
        try:
            value = datetime.datetime.fromisoformat(at)
        except (TypeError, ValueError):
            return at
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC8)
    return value.astimezone(UTC8).replace(tzinfo=None).isoformat(timespec="seconds")


class AstrBotSourceView:
    """Normalize extraction's evidence read view without rewriting Sources."""

    def __init__(self, sources: SourceStore) -> None:
        self.sources = sources

    def append_sources(self, sources: list[Source]) -> int:
        return self.sources.append_sources(sources)

    def recent_sources(self, *, since: str, limit: int) -> list[Source]:
        return [
            replace(source, at=utc8_time(source.at))
            for source in self.sources.recent_sources(since=since, limit=limit)
        ]

    def source_umo(self, source_id: str) -> str:
        return self.sources.source_umo(source_id)

    def source_umos(self, source_ids: list[str]) -> dict[str, str]:
        return self.sources.source_umos(source_ids)

    def sources_by_ids(self, source_ids: list[str]) -> dict[str, Source]:
        return {
            key: replace(source, at=utc8_time(source.at))
            for key, source in self.sources.sources_by_ids(source_ids).items()
        }


class AstrBotRunRecorder(RunRecorder):
    """Normalize at the host boundary, then reuse every existing write path."""

    def record_user(self, *, at: str = "", **fields: Any) -> RecordedTurn:
        return super().record_user(at=utc8_time(at), **fields)

    def record_reply(self, *, at: str = "", **fields: Any) -> RecordedReply:
        return super().record_reply(at=utc8_time(at), **fields)

    def record_delivery(self, *, at: str = "", **fields: Any) -> None:
        super().record_delivery(at=utc8_time(at), **fields)

    def record_error(self, *, at: str = "", **fields: Any) -> None:
        super().record_error(at=utc8_time(at), **fields)


class AstrBotBuffer(Buffer):
    """Use UTC+8 views and age signals without changing the kernel Buffer."""

    def add(
        self, umo: str, text: str, sender: str = "", source_id: str = "",
        at: str = "", *, source: Source | None = None, **fields: Any,
    ) -> DialogueTurn | None:
        return super().add(
            umo, text, sender, source_id,
            utc8_time(at or (source.at if source is not None else "")),
            source=source, **fields,
        )

    def _load_projection(self) -> None:
        super()._load_projection()
        self.items = [replace(turn, at=utc8_time(turn.at)) for turn in self.items]
        self.last_ts = max(self._timestamps(), default=0.0)

    def _timestamps(self) -> list[float]:
        stamps = []
        for turn in self.items:
            try:
                value = datetime.datetime.fromisoformat(utc8_time(turn.at))
                stamps.append(value.replace(tzinfo=UTC8).timestamp())
            except (TypeError, ValueError):
                continue
        return stamps

    def oldest_topic_age(self) -> float:
        stamps = self._timestamps()
        return max(0.0, time.time() - min(stamps)) if stamps else 0.0
