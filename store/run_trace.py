"""Bounded JSONL trace adapter. No message text, database migration or network I/O."""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

try:
    from ..app.runtime.trace_data import FILTERS, clean_event, project_runs
except ImportError:  # Standalone tests use the repository as the import root.
    from app.runtime.trace_data import FILTERS, clean_event, project_runs


class TraceStore:
    def __init__(self, path: Path, *, retention_days: int = 7, max_rows: int = 5000,
                 clock=time.time) -> None:
        self.path = Path(path)
        self.retention_days = max(1, min(365, int(retention_days)))
        self.max_rows = max(1, min(5000, int(max_rows)))
        self.clock = clock
        self.started = clock()
        self.events: list[dict] = []
        self.persistence_error = False
        self._lock = threading.RLock()
        try:
            if self.path.exists():
                with self.path.open("rb") as stream:
                    while line := stream.readline(262145):
                        if len(line) > 262144:
                            while line and not line.endswith(b"\n"):
                                line = stream.readline(262145)
                            continue
                        try:
                            self.events.append(clean_event(json.loads(line)))
                            self.events = self.events[-self.max_rows:]
                        except (ValueError, TypeError, KeyError, AttributeError):
                            continue
                self.events = self._retained(self.events)
                self._persist(self.events)
        except OSError:
            self.persistence_error = True

    def _retained(self, rows: list[dict]) -> list[dict]:
        cutoff = self.clock() - self.retention_days * 86400
        return [r for r in rows if datetime.fromisoformat(r["at"]).timestamp() >= cutoff][-self.max_rows:]

    def _persist(self, rows: list[dict]) -> None:
        """Atomic compaction prevents a failed rewrite from destroying old traces."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=self.path.parent, prefix=".run-trace-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                for row in rows:
                    stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def append(self, row: dict) -> None:
        with self._lock:
            try:
                row = clean_event(row)
                combined = [*self.events, row]
                rows = self._retained(combined)
                compact = len(rows) != len(combined)
                if len(combined) > self.max_rows:
                    # Evict up to 1% in a batch to avoid rewriting 5000 rows per hook.
                    rows = rows[-(self.max_rows - max(1, self.max_rows // 100) + 1):]
                if compact or self.persistence_error or not self.path.exists():
                    self._persist(rows)
                else:
                    # A failed append is repaired from the last good snapshot on retry.
                    with self.path.open("a", encoding="utf-8") as stream:
                        stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                self.events = rows
                self.persistence_error = False
            except (OSError, ValueError, TypeError, KeyError):
                self.persistence_error = True

    def snapshot(self, state: str = "all") -> dict:
        if state not in FILTERS:
            raise ValueError("unknown_trace_filter")
        with self._lock:
            rows = self._retained(self.events)
            if len(rows) != len(self.events):
                try:
                    self._persist(rows)
                    self.events = rows
                    self.persistence_error = False
                except OSError:
                    self.persistence_error = True
            runs = project_runs(rows, self.started)
            if state != "all":
                runs = [r for r in runs if state in r["flags"]]
            visible = {r["id"] for r in runs}
            return {"runs": runs, "events": [r for r in rows if r["run_id"] in visible],
                    "capacity": self.max_rows, "retention_days": self.retention_days,
                    "persistence_error": self.persistence_error}
