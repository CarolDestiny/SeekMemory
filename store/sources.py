"""Immutable Source persistence repository."""

from __future__ import annotations

import sqlite3
from typing import Any

try:
    from .sqlite import SqliteRepository, dump_json, load_json_object, now_iso
except ImportError:
    from sqlite import SqliteRepository, dump_json, load_json_object, now_iso

try:
    from ..core.source import Source
except ImportError:
    from core.source import Source


def source_flags(source: Source) -> dict[str, Any]:
    return {
        "turn_id": source.turn_id,
        "speaker_id": source.speaker_id,
        "reply_to": source.reply_to,
        "metadata": source.metadata,
    }


def write_source_conn(
    conn: sqlite3.Connection,
    source: Source,
    at: str = "",
) -> int:
    """Insert one immutable Source inside a caller-owned transaction."""
    source.validate()
    moment = source.at or at or now_iso()
    content_hash = source.content_hash
    conn.execute(
        "INSERT OR IGNORE INTO blobs(hash, content, at) VALUES(?, ?, ?)",
        (content_hash, source.text, moment),
    )
    cur = conn.execute(
        "INSERT OR IGNORE INTO sources(id, umo, at, role, blob, flags) "
        "VALUES(?, ?, ?, ?, ?, ?)",
        (
            source.id,
            source.session_id,
            moment,
            source.role,
            content_hash,
            dump_json(source_flags(source)),
        ),
    )
    return int(cur.rowcount or 0)


class SourceRepository(SqliteRepository):
    """Own immutable Source rows and Source-only projections."""

    def append_sources(self, sources: list[Source]) -> int:
        written = 0
        with self.conn:
            for source in sources:
                written += write_source_conn(self.conn, source)
        return written

    @staticmethod
    def _source_from_row(row: sqlite3.Row) -> Source:
        flags = load_json_object(row["flags"])
        metadata = flags.get("metadata")
        return Source(
            str(row["id"]),
            str(flags.get("turn_id") or ""),
            str(row["umo"]),
            str(flags.get("speaker_id") or ""),
            str(row["role"]),
            str(row["text"] or ""),
            str(row["at"] or ""),
            str(flags.get("reply_to") or "") or None,
            metadata if isinstance(metadata, dict) else {},
        )

    def recent_sources(self, *, since: str, limit: int) -> list[Source]:
        """Return globally ordered recent Sources, bounded by time and count."""
        if int(limit) <= 0:
            return []
        rows = self.conn.execute(
            "SELECT s.id, s.umo, s.at, s.role, s.flags, b.content AS text "
            "FROM sources s JOIN blobs b ON b.hash = s.blob "
            "WHERE s.at >= ? ORDER BY s.at DESC, s.id DESC LIMIT ?",
            (str(since or ""), int(limit)),
        ).fetchall()
        return [self._source_from_row(row) for row in rows]

    def source_umo(self, source_id: str) -> str:
        row = self.conn.execute(
            "SELECT umo FROM sources WHERE id = ?", (source_id,)
        ).fetchone()
        return str(row["umo"]) if row is not None else ""

    def source_umos(self, source_ids: list[str]) -> dict[str, str]:
        ids = [str(value) for value in source_ids if value]
        if not ids:
            return {}
        marks = ",".join("?" for _ in ids)
        rows = self.conn.execute(
            f"SELECT id, umo FROM sources WHERE id IN ({marks})", ids
        ).fetchall()
        return {str(row["id"]): str(row["umo"]) for row in rows}

    def sources_by_ids(self, source_ids: list[str]) -> dict[str, Source]:
        ids: list[str] = []
        for value in source_ids:
            text = str(value or "").strip()
            if text and text not in ids:
                ids.append(text)
        if not ids:
            return {}
        marks = ",".join("?" for _ in ids)
        rows = self.conn.execute(
            "SELECT s.id, s.umo, s.at, s.role, s.flags, b.content AS text "
            "FROM sources s JOIN blobs b ON b.hash = s.blob "
            f"WHERE s.id IN ({marks})",
            ids,
        ).fetchall()
        return {
            str(row["id"]): self._source_from_row(row)
            for row in rows
        }

    def latest_user_source(self, session_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT s.id, s.umo, s.at, s.role, b.content AS text "
            "FROM sources s JOIN blobs b ON b.hash = s.blob "
            "WHERE s.umo = ? AND s.role = 'user' "
            "ORDER BY s.at DESC, s.id DESC LIMIT 1",
            (str(session_id or ""),),
        ).fetchone()
        return dict(row) if row is not None else None
