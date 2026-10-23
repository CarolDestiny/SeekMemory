"""Runtime episode recording."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class RuntimeEpisode:
    session_id: str
    at: str
    decision: str
    reason: str
    action: str
    delivered: bool
    response_chars: int = 0
    tool_calls: tuple[str, ...] = ()
    outcome: str = ""
    error: str = ""
    user_source_id: str = ""
    assistant_source_id: str = ""


class EpisodeSink(Protocol):
    def append(self, episode: RuntimeEpisode) -> None: ...


class EpisodeRecorder:
    def __init__(self, sink: EpisodeSink) -> None:
        self.sink = sink

    def record(self, episode: RuntimeEpisode) -> None:
        self.sink.append(episode)


class JsonlEpisodeStore:
    """Append-only local episode log; never stores message bodies."""

    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self.last_error = ""

    def append(self, episode: RuntimeEpisode) -> None:
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(asdict(episode), ensure_ascii=False,
                                            sort_keys=True) + "\n")
                self.last_error = ""
            except Exception as exc:  # noqa: BLE001 - episode logging is fail-open
                self.last_error = type(exc).__name__


class DBEpisodeStore:
    """Persist runtime episodes through the project's SQLite DB facade."""

    def __init__(self, db) -> None:
        self.db = db

    def append(self, episode: RuntimeEpisode) -> None:
        payload = asdict(episode)
        payload["id"] = f"ep_{time.time_ns()}"
        payload["tool_calls"] = list(episode.tool_calls)
        self.db.append_runtime_episode(payload)
