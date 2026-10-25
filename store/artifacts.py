"""Artifact persistence and versioned commit repository."""

from __future__ import annotations

import json

try:
    from .artifact_codec import (
        SELECT_SQL,
        UPSERT_SQL,
        node_values,
        payload_blob,
        row_to_artifact,
        stored_header,
    )
    from .ledger import append_ledger_conn
    from .sqlite import SqliteRepository, dump_json, now_iso
except ImportError:
    from artifact_codec import (
        SELECT_SQL,
        UPSERT_SQL,
        node_values,
        payload_blob,
        row_to_artifact,
        stored_header,
    )
    from ledger import append_ledger_conn
    from sqlite import SqliteRepository, dump_json, now_iso

try:
    from ..core.artifact import Artifact
    from ..core.versioning import StateEvent, VersionError, assert_next_revision
except ImportError:
    from core.artifact import Artifact
    from core.versioning import StateEvent, VersionError, assert_next_revision


class ArtifactRepository(SqliteRepository):
    """Own Artifact rows, versions, evidence, edges and state events."""

    def upsert(self, art: Artifact) -> None:
        """Low-level seed/benchmark write; production uses commit()."""
        header, now = art.header, now_iso()
        content, blob = payload_blob(art.payload)
        args = node_values(header, art.payload, now, blob)
        header_blob = stored_header(header)
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO blobs(hash, content, at) VALUES(?, ?, ?)",
                (blob, content, now),
            )
            self.conn.execute(UPSERT_SQL, args)
            self.conn.execute(
                "INSERT OR IGNORE INTO versions(entity, revision, blob, header, at) "
                "VALUES(?, ?, ?, ?, ?)",
                (header.id, int(header.revision), blob, header_blob, now),
            )
            self.conn.execute(
                "INSERT OR IGNORE INTO artifact_versions("
                "entity, revision, op, blob, header, at) "
                "VALUES(?, ?, ?, ?, ?, ?)",
                (header.id, int(header.revision), "upsert", blob, header_blob, now),
            )

    def count(self, family: str | None = None) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS c FROM nodes WHERE ? IS NULL OR family = ?",
            (family, family),
        ).fetchone()
        return int(row["c"]) if row is not None else 0

    def commit(
        self,
        art: Artifact,
        *,
        expected_revision: int,
        op: str,
        reason: str = "",
        source_ids: tuple[str, ...] = (),
        state_events: tuple[StateEvent, ...] = (),
    ) -> None:
        if op not in (
            "create",
            "revise",
            "reinforce",
            "deliver",
            "merge",
            "forget",
            "promote",
        ):
            raise ValueError(f"unknown commit op: {op}")
        with self.conn:
            self._commit_conn(
                art,
                expected_revision=expected_revision,
                op=op,
                reason=reason,
                source_ids=source_ids,
                state_events=state_events,
            )

    def commit_many(
        self,
        writes: list[tuple[Artifact, int, tuple[str, ...]]],
        *,
        op: str,
        reason: str = "",
    ) -> None:
        if not writes:
            return
        with self.conn:
            for art, expected_revision, source_ids in writes:
                self._commit_conn(
                    art,
                    expected_revision=expected_revision,
                    op=op,
                    reason=reason,
                    source_ids=source_ids,
                )

    def history(self, node_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT v.revision, v.op, v.at, b.content FROM artifact_versions v "
            "JOIN blobs b ON v.blob = b.hash WHERE v.entity = ? "
            "ORDER BY v.revision ASC",
            (node_id,),
        ).fetchall()
        out = []
        for revision, op, at, content in rows:
            try:
                payload = json.loads(content)
            except Exception:  # noqa: BLE001 - malformed old rows are skipped
                continue
            out.append(
                {
                    "revision": int(revision),
                    "op": str(op),
                    "at": str(at),
                    "payload": payload,
                }
            )
        return out

    def get(self, node_id: str) -> Artifact | None:
        row = self.conn.execute(
            SELECT_SQL + " WHERE n.id = ?", (node_id,)
        ).fetchone()
        return row_to_artifact(row)

    def by_source_ids(self, source_ids: list[str]) -> list[Artifact]:
        ids: list[str] = []
        for value in source_ids:
            text = str(value or "").strip()
            if text and text not in ids:
                ids.append(text)
        if not ids:
            return []
        marks = ",".join("?" for _ in ids)
        rows = self.conn.execute(
            "SELECT DISTINCT n.*, b.content AS blob_content FROM nodes n "
            "LEFT JOIN blobs b ON b.hash = n.blob "
            "JOIN artifact_evidence ae ON ae.entity = n.id "
            "AND ae.revision = n.revision "
            f"WHERE n.state = 'active' AND ae.source IN ({marks}) "
            "ORDER BY n.created_at, n.id",
            ids,
        ).fetchall()
        return [art for art in map(row_to_artifact, rows) if art is not None]

    def list(
        self, family: str | None = None, state: str | None = None
    ) -> list[Artifact]:
        sql, args = SELECT_SQL, []
        for column, value in (("family", family), ("state", state)):
            if value is not None:
                sql += (" WHERE " if not args else " AND ") + f"n.{column} = ?"
                args.append(value)
        rows = self.conn.execute(sql + " ORDER BY n.created_at, n.id", args).fetchall()
        return [art for art in map(row_to_artifact, rows) if art is not None]

    def set_parent(self, node_id: str, parent_id: str | None) -> None:
        """Persist the optional tree parent column owned by this repository."""
        with self.conn:
            self.conn.execute(
                "UPDATE nodes SET parent = ?, updated_at = ? WHERE id = ?",
                (parent_id, now_iso(), str(node_id)),
            )

    def add_edge(self, src: str, dst: str, kind: str, weight: float) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO edges(src, dst, kind, weight) VALUES(?, ?, ?, ?) "
                "ON CONFLICT(src, dst, kind) DO UPDATE SET weight=excluded.weight",
                (src, dst, kind, float(weight)),
            )

    def edges_of(self, node_id: str) -> list[tuple[str, str, float]]:
        rows = self.conn.execute(
            "SELECT dst AS other, kind, weight FROM edges WHERE src = ? "
            "UNION SELECT src AS other, kind, weight FROM edges WHERE dst = ?",
            (node_id, node_id),
        ).fetchall()
        return [(str(r["other"]), str(r["kind"]), float(r["weight"])) for r in rows]

    def inspect_record(self, node_id: str) -> dict:
        versions = self.conn.execute(
            "SELECT v.revision, v.op, v.at, v.blob, v.header, b.content "
            "FROM artifact_versions v LEFT JOIN blobs b ON b.hash = v.blob "
            "WHERE v.entity = ? ORDER BY v.revision DESC",
            (node_id,),
        ).fetchall()
        sources = self.conn.execute(
            "SELECT s.id, s.umo, s.at, s.role, s.blob, s.flags, b.content AS text "
            "FROM sources s LEFT JOIN blobs b ON b.hash = s.blob "
            "WHERE s.id IN (SELECT source FROM evidence WHERE node = ? "
            "UNION SELECT source FROM artifact_evidence WHERE entity = ?) "
            "ORDER BY s.at",
            (node_id, node_id),
        ).fetchall()
        return {
            "versions": [dict(row) for row in versions],
            "sources": [dict(row) for row in sources],
        }

    def _commit_conn(
        self,
        art: Artifact,
        *,
        expected_revision: int,
        op: str,
        reason: str,
        source_ids: tuple[str, ...] = (),
        state_events: tuple[StateEvent, ...] = (),
    ) -> None:
        header = art.header
        now = now_iso()
        row = self.conn.execute(
            "SELECT revision FROM nodes WHERE id = ?", (header.id,)
        ).fetchone()
        current = int(row["revision"]) if row is not None else 0
        if current != int(expected_revision):
            raise VersionError(
                f"revision conflict: expected {expected_revision}, current {current}"
            )
        previous = self.get(header.id) if current else None
        assert_next_revision(previous, art)
        content, blob = payload_blob(art.payload)
        args = node_values(header, art.payload, now, blob)
        header_blob = stored_header(header)
        self.conn.execute(
            "INSERT OR IGNORE INTO blobs(hash, content, at) VALUES(?, ?, ?)",
            (blob, content, now),
        )
        self.conn.execute(UPSERT_SQL, args)
        self.conn.execute(
            "INSERT INTO versions(entity, revision, blob, header, at) "
            "VALUES(?, ?, ?, ?, ?)",
            (header.id, int(header.revision), blob, header_blob, now),
        )
        self.conn.execute(
            "INSERT INTO artifact_versions(entity, revision, op, blob, header, at) "
            "VALUES(?, ?, ?, ?, ?, ?)",
            (header.id, int(header.revision), op, blob, header_blob, now),
        )
        for source_id in source_ids:
            self.conn.execute(
                "INSERT OR IGNORE INTO artifact_evidence(entity, revision, source) "
                "VALUES(?, ?, ?)",
                (header.id, int(header.revision), str(source_id)),
            )
        for event in state_events:
            event.validate()
            self.conn.execute(
                "INSERT OR IGNORE INTO state_events("
                "id, entity, revision_seen, op, delta, at) "
                "VALUES(?, ?, ?, ?, ?, ?)",
                (
                    event.id,
                    event.entity_id,
                    event.revision_seen,
                    event.op,
                    dump_json(event.delta),
                    event.at or now,
                ),
            )
        before = str(current) if current else None
        append_ledger_conn(
            self.conn,
            op,
            header.id,
            before,
            str(header.revision),
            reason,
            now,
        )
