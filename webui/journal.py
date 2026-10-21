"""Bounded structured lifecycle logs without conversation or model payloads."""

from __future__ import annotations

import json
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


class Journal:
    """Keep recent operational events in memory and a rotating JSONL file."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.events: deque[dict[str, str]] = deque(maxlen=500)
        self.persistence_error = False
        try:
            for file in (path.with_suffix(".jsonl.1"), path):
                if file.exists():
                    with file.open("rb") as stream:
                        stream.seek(max(0, file.stat().st_size - 1024 * 1024))
                        for line in stream.read().splitlines():
                            try:
                                row = json.loads(line)
                                if isinstance(row, dict) and all(
                                    isinstance(row.get(key), str)
                                    for key in (
                                        "id",
                                        "at",
                                        "kind",
                                        "status",
                                        "message",
                                        "taskId",
                                    )
                                ):
                                    self.events.append(row)
                            except (ValueError, UnicodeError):
                                continue
        except OSError:
            self.persistence_error = True
        unfinished: dict[str, dict[str, str]] = {}
        for event in self.events:
            if event["taskId"] and event["status"] in {
                "queued",
                "running",
                "succeeded",
                "failed",
                "cancelled",
                "interrupted",
            }:
                unfinished[event["taskId"]] = event
        for task_id, event in unfinished.items():
            if event["status"] in {"queued", "running"}:
                self.record(
                    event["kind"], "interrupted", "Previous process stopped", task_id
                )

    def record(self, kind: str, status: str, message: str, task_id: str = "") -> None:
        """Append an event without allowing logging failures to break chat.

        Args:
            kind: Operation category.
            status: Lifecycle state or log severity.
            message: Operational summary; never pass conversation content.
            task_id: Correlation ID for a background operation.
        """
        row = {
            "id": uuid4().hex,
            "at": datetime.now(timezone.utc).isoformat(),
            "kind": kind,
            "status": status,
            "message": message[:1000],
            "taskId": task_id,
        }
        self.events.append(row)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists() and self.path.stat().st_size > 1024 * 1024:
                self.path.replace(self.path.with_suffix(".jsonl.1"))
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            self.persistence_error = False
        except OSError:
            self.persistence_error = True
