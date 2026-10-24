"""Ledger hash chain and repository."""

from __future__ import annotations

import hashlib
import json
import sqlite3

try:
    from .sqlite import SqliteRepository, now_iso
except ImportError:
    from sqlite import SqliteRepository, now_iso


def chain_payload(
    at: str,
    op: str,
    entity: str,
    before: str | None,
    after: str | None,
    reason: str,
) -> str:
    return json.dumps(
        [at, op, entity, before, after, reason],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def chain_hash(prev_hash: str, payload: str) -> str:
    return hashlib.sha256((prev_hash + payload).encode("utf-8")).hexdigest()[:16]


def append_ledger_conn(
    conn: sqlite3.Connection,
    op: str,
    entity: str,
    before: str | None,
    after: str | None,
    reason: str,
    at: str = "",
) -> None:
    """Append inside a caller-owned transaction."""
    moment = at or now_iso()
    row = conn.execute(
        "SELECT self_hash FROM ledger ORDER BY seq DESC LIMIT 1"
    ).fetchone()
    previous = str(row["self_hash"]) if row is not None else ""
    payload = chain_payload(moment, op, entity, before, after, reason)
    conn.execute(
        "INSERT INTO ledger(at, op, entity, before_hash, after_hash, reason, "
        "prev_hash, self_hash) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
        (
            moment,
            op,
            entity,
            before,
            after,
            reason,
            previous,
            chain_hash(previous, payload),
        ),
    )


class LedgerRepository(SqliteRepository):
    """Read and append the append-only ledger table."""

    def last_hash(self) -> str:
        row = self.conn.execute(
            "SELECT self_hash FROM ledger ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        return str(row["self_hash"]) if row is not None else ""

    def append(
        self,
        op: str,
        entity: str,
        before: str | None,
        after: str | None,
        reason: str,
    ) -> None:
        with self.conn:
            append_ledger_conn(self.conn, op, entity, before, after, reason)

    def entries(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT at, op, entity, before_hash, after_hash, reason, prev_hash, "
            "self_hash FROM ledger ORDER BY seq"
        ).fetchall()


class Ledger:
    """Validate the repository's hash chain."""

    def __init__(self, repository: LedgerRepository) -> None:
        self.repository = repository

    def append(
        self,
        op: str,
        entity: str,
        before: str | None = None,
        after: str | None = None,
        reason: str = "",
    ) -> str:
        self.repository.append(op, entity, before, after, reason)
        return self.last_hash()

    def last_hash(self) -> str:
        return self.repository.last_hash()

    def verify(self) -> bool:
        previous = ""
        for row in self.repository.entries():
            payload = chain_payload(
                str(row["at"]),
                str(row["op"]),
                str(row["entity"]),
                row["before_hash"],
                row["after_hash"],
                str(row["reason"]),
            )
            expected = chain_hash(previous, payload)
            if str(row["prev_hash"]) != previous or str(row["self_hash"]) != expected:
                return False
            previous = expected
        return True
