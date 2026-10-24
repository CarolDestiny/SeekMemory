"""Artifact row serialization and reconstruction."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

try:
    from .sqlite import dump_json, load_json_object, pick_dataclass_fields
except ImportError:
    from sqlite import dump_json, load_json_object, pick_dataclass_fields

try:
    from ..core.artifact import Artifact, Header, Lineage, Strength, TimeSpan
except ImportError:
    from core.artifact import Artifact, Header, Lineage, Strength, TimeSpan

SELECT_SQL = (
    "SELECT n.*, b.content AS blob_content FROM nodes n "
    "LEFT JOIN blobs b ON b.hash = n.blob"
)
UPSERT_SQL = (
    "INSERT INTO nodes(id, family, level, parent, blob, state, scope, strength, time, "
    "said_by, shareable, created_at, updated_at, revision, lineage, subject_id) "
    "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
    "family=excluded.family, level=excluded.level, "
    "parent=COALESCE(excluded.parent, nodes.parent), blob=excluded.blob, "
    "state=excluded.state, scope=excluded.scope, strength=excluded.strength, "
    "time=excluded.time, said_by=excluded.said_by, shareable=excluded.shareable, "
    "revision=excluded.revision, lineage=excluded.lineage, subject_id=excluded.subject_id, "
    "updated_at=excluded.updated_at, "
    "created_at=CASE WHEN nodes.created_at = '' THEN excluded.created_at "
    "ELSE nodes.created_at END"
)


def payload_blob(payload: dict[str, Any]) -> tuple[str, str]:
    content = dump_json(payload)
    return content, hashlib.sha256(content.encode("utf-8")).hexdigest()


def node_values(header: Header, payload: dict[str, Any], now: str,
                blob: str | None = None) -> tuple:
    level, parent = payload.get("level"), payload.get("parent")
    return (
        header.id,
        header.family,
        level if isinstance(level, str) else None,
        parent if isinstance(parent, str) else None,
        blob or payload_blob(payload)[1],
        header.state,
        header.scope,
        dump_json(header.strength),
        dump_json(header.time),
        header.said_by,
        header.shareable,
        header.time.created or now,
        header.time.updated or now,
        int(header.revision),
        dump_json(header.lineage),
        header.subject_id,
    )


def stored_header(header: Header) -> str:
    return dump_json(
        {
            "state": header.state,
            "scope": header.scope,
            "strength": dump_json(header.strength),
            "time": dump_json(header.time),
            "said_by": header.said_by,
            "revision": int(header.revision),
            "lineage": dump_json(header.lineage),
            "subject_id": header.subject_id,
        }
    )


def row_to_artifact(row: sqlite3.Row | None) -> Artifact | None:
    if row is None or not row["blob_content"]:
        return None
    try:
        lineage = pick_dataclass_fields(Lineage, load_json_object(row["lineage"]))
        for key in ("sources", "derived_from"):
            lineage[key] = tuple(lineage.get(key) or ())
        header = Header(
            id=str(row["id"]),
            family=str(row["family"]),
            revision=int(row["revision"] or 1),
            state=str(row["state"]),
            scope=str(row["scope"]),
            lineage=Lineage(**lineage),
            strength=Strength(
                **pick_dataclass_fields(Strength, load_json_object(row["strength"]))
            ),
            time=TimeSpan(
                **pick_dataclass_fields(TimeSpan, load_json_object(row["time"]))
            ),
            said_by=str(row["said_by"]),
            shareable=str(row["shareable"]),
            subject_id=str(row["subject_id"] or ""),
        )
        payload = json.loads(row["blob_content"])
    except (TypeError, ValueError, KeyError):
        return None
    return Artifact(header=header, payload=payload if isinstance(payload, dict) else {})
