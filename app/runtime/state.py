"""Session state stores for the runtime."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import asdict
from pathlib import Path

from .contracts import SessionState


class InMemoryStateStore:
    """Small deterministic store used by tests and ephemeral hosts."""

    def __init__(self) -> None:
        self._items: dict[str, SessionState] = {}

    def get(self, session_id: str) -> SessionState:
        key = str(session_id or "")
        state = self._items.get(key)
        if state is None:
            state = SessionState(session_id=key)
            self._items[key] = state
        return state

    def put(self, state: SessionState) -> None:
        self._items[str(state.session_id or "")] = state


class JsonStateStore:
    """Atomic JSON-backed state store for plugin data directories."""

    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self._items: dict[str, dict] | None = None
        self.last_error = ""

    def _load(self) -> dict[str, dict]:
        if self._items is not None:
            return self._items
        self._items = {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return self._items
        except Exception as exc:  # noqa: BLE001 - runtime state is fail-open
            self.last_error = type(exc).__name__
            return self._items
        if isinstance(data, dict):
            self._items = {
                str(key): value for key, value in data.items()
                if isinstance(value, dict)
            }
        return self._items

    def get(self, session_id: str) -> SessionState:
        key = str(session_id or "")
        with self._lock:
            raw = self._load().get(key)
            if not isinstance(raw, dict):
                return SessionState(session_id=key)
            data = {key: raw.get(key) for key in SessionState.__dataclass_fields__}
            try:
                return SessionState(**data)
            except TypeError:
                return SessionState(session_id=key)

    def put(self, state: SessionState) -> None:
        key = str(state.session_id or "")
        with self._lock:
            items = self._load()
            items[key] = asdict(state)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(items, ensure_ascii=False, sort_keys=True)
            try:
                fd, temp = tempfile.mkstemp(prefix=".runtime-state-", dir=str(self.path.parent))
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as handle:
                        handle.write(payload)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(temp, self.path)
                    self.last_error = ""
                finally:
                    if os.path.exists(temp):
                        os.unlink(temp)
            except Exception as exc:  # noqa: BLE001 - runtime state failure is not fatal
                self.last_error = type(exc).__name__


class DBStateStore:
    """Persist SessionState through the project's SQLite DB facade."""

    def __init__(self, db) -> None:
        self.db = db
        self.last_error = ""

    def get(self, session_id: str) -> SessionState:
        key = str(session_id or "")
        try:
            raw = self.db.get_runtime_state(key)
        except Exception as exc:  # noqa: BLE001 - runtime state is fail-open
            self.last_error = type(exc).__name__
            return SessionState(session_id=key)
        if not isinstance(raw, dict) or not raw:
            return SessionState(session_id=key)
        data = {
            name: raw[name]
            for name in SessionState.__dataclass_fields__
            if name in raw and raw[name] is not None
        }
        data["session_id"] = key
        try:
            return SessionState(**data)
        except TypeError:
            return SessionState(session_id=key)

    def put(self, state: SessionState) -> None:
        try:
            self.db.put_runtime_state(str(state.session_id or ""), asdict(state))
            self.last_error = ""
        except Exception as exc:  # noqa: BLE001 - runtime state is fail-open
            self.last_error = type(exc).__name__
