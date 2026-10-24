"""Append-only runtime episode repository."""

from __future__ import annotations

import datetime
import json
import time
from typing import Any

try:
    from .sqlite import SqliteRepository, now_iso
except ImportError:
    from sqlite import SqliteRepository, now_iso


class RuntimeEpisodeRepository(SqliteRepository):
    """Persist content-free runtime audit rows."""

    def append(self, episode: dict[str, Any]) -> str:
        episode_id = str(episode.get("id") or f"ep_{time.time_ns()}")
        tool_calls = json.dumps(
            list(episode.get("tool_calls") or ()), ensure_ascii=False
        )
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO runtime_episodes("
                "id, at, session_id, decision, reason, action, delivered, "
                "response_chars, tool_calls, outcome, error, user_source_id, "
                "assistant_source_id, run_id) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    episode_id,
                    str(episode.get("at") or now_iso()),
                    str(episode.get("session_id") or ""),
                    str(episode.get("decision") or ""),
                    str(episode.get("reason") or ""),
                    str(episode.get("action") or ""),
                    int(bool(episode.get("delivered"))),
                    int(episode.get("response_chars") or 0),
                    tool_calls,
                    str(episode.get("outcome") or ""),
                    str(episode.get("error") or ""),
                    str(episode.get("user_source_id") or ""),
                    str(episode.get("assistant_source_id") or ""),
                    str(episode.get("run_id") or ""),
                ),
            )
        return episode_id

    def list(self, session_id: str = "", limit: int = 100) -> list[dict[str, Any]]:
        size = max(1, min(1000, int(limit)))
        if session_id:
            rows = self.conn.execute(
                "SELECT * FROM runtime_episodes WHERE session_id = ? "
                "ORDER BY at DESC, rowid DESC LIMIT ?",
                (str(session_id), size),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM runtime_episodes ORDER BY at DESC, rowid DESC LIMIT ?",
                (size,),
            ).fetchall()
        return [dict(row) for row in rows]

    def prune(self, retention_days: int = 30, max_rows: int = 5000) -> int:
        days = max(0, int(retention_days))
        limit = max(1, int(max_rows))
        deleted = 0
        with self.conn:
            if days:
                cutoff = (
                    datetime.datetime.now() - datetime.timedelta(days=days)
                ).isoformat(timespec="seconds")
                cur = self.conn.execute(
                    "DELETE FROM runtime_episodes WHERE at < ?", (cutoff,)
                )
                deleted += int(cur.rowcount or 0)
            cur = self.conn.execute(
                "DELETE FROM runtime_episodes WHERE id IN ("
                "SELECT id FROM runtime_episodes ORDER BY at DESC, id DESC "
                "LIMIT -1 OFFSET ?)",
                (limit,),
            )
            deleted += int(cur.rowcount or 0)
        return deleted
