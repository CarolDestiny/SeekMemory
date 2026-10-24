"""Cross-domain read-only store metrics."""

from __future__ import annotations

import datetime

try:
    from .extraction import ExtractionRepository
    from .sqlite import SqliteRepository, age_seconds, load_json_object, parse_time
except ImportError:
    from extraction import ExtractionRepository
    from sqlite import SqliteRepository, age_seconds, load_json_object, parse_time


class StoreMetricsRepository(SqliteRepository):
    """Return content-free counters for capacity admission."""

    def __init__(self, db, extraction: ExtractionRepository) -> None:
        super().__init__(db)
        self.extraction = extraction

    def capacity_usage(self, now: str = "") -> dict[str, int | float]:
        source = self.conn.execute(
            "SELECT COUNT(*) AS rows, "
            "COALESCE(SUM(LENGTH(CAST(b.content AS BLOB))), 0) AS bytes "
            "FROM sources s JOIN blobs b ON b.hash = s.blob"
        ).fetchone()
        active = self.conn.execute(
            "SELECT COUNT(*) AS rows, "
            "COALESCE(SUM(LENGTH(CAST(b.content AS BLOB))), 0) AS bytes "
            "FROM nodes n JOIN blobs b ON b.hash = n.blob "
            "WHERE n.state = 'active'"
        ).fetchone()
        pending = self.conn.execute(
            "SELECT COUNT(*) AS rows, MIN(created_at) AS oldest "
            "FROM extraction_state WHERE state IN ('pending', 'retrying')"
        ).fetchone()
        counts = self.extraction.queue_counts()
        page_count = int(self.conn.execute("PRAGMA page_count").fetchone()[0] or 0)
        page_size = int(self.conn.execute("PRAGMA page_size").fetchone()[0] or 0)
        current = parse_time(now) or datetime.datetime.now()
        oldest = parse_time(str(pending["oldest"] or ""))
        pending_age = age_seconds(oldest, current)
        expired = 0
        for row in self.conn.execute(
            "SELECT time FROM nodes WHERE state = 'active'"
        ).fetchall():
            span = load_json_object(row["time"])
            deadline = span.get("expires") or span.get("valid_to")
            parsed = parse_time(str(deadline or ""))
            if parsed is not None and parsed.date() < current.date():
                expired += 1
        return {
            "db_bytes": page_count * page_size,
            "source_rows": int(source["rows"] or 0),
            "source_bytes": int(source["bytes"] or 0),
            "pending_rows": int(pending["rows"] or 0),
            "pending_oldest_age_seconds": pending_age,
            "deferred_rows": int(counts.get("deferred", 0)),
            "dead_rows": int(counts.get("dead", 0)),
            "artifact_count": int(active["rows"] or 0),
            "artifact_bytes": int(active["bytes"] or 0),
            "expired_artifacts": expired,
        }
