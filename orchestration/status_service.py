"""Read-only memory status queries for the management UI."""

from __future__ import annotations

import json


class StatusService:
    """Expose persona revisions without leaking source text."""

    def __init__(self, *, db) -> None:
        self.db = db

    @staticmethod
    def json_object(raw: object) -> dict:
        value = raw
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (TypeError, ValueError):
                return {}
        return value if isinstance(value, dict) else {}

    @classmethod
    def header_evidence(cls, raw_header: object) -> tuple[list[str], list[str]]:
        header = cls.json_object(raw_header)
        lineage = cls.json_object(header.get("lineage"))

        def ids(*names: str) -> list[str]:
            for name in names:
                value = lineage.get(name)
                if isinstance(value, str):
                    try:
                        value = json.loads(value)
                    except (TypeError, ValueError):
                        continue
                if not isinstance(value, (list, tuple)):
                    continue
                out: list[str] = []
                for item in value:
                    if not isinstance(item, str):
                        continue
                    text = item.strip()
                    if text and text not in out:
                        out.append(text)
                return out
            return []

        return ids("derived_from", "derivedFrom"), ids("sources", "sourceIds")

    def persona(self) -> dict | None:
        if self.db is None:
            return None
        active = [art for art in self.db.list(family="persona", state="active")]
        if not active:
            return None
        current = max(active, key=lambda art: art.header.revision)
        evidence: dict[int, tuple[list[str], list[str]]] = {}
        inspected = self.db.inspect_record(current.header.id)
        for row in inspected.get("versions", []):
            try:
                revision = int(row.get("revision") or 0)
            except (TypeError, ValueError):
                continue
            evidence[revision] = self.header_evidence(row.get("header"))
        revisions = []
        for row in self.db.history(current.header.id):
            revision = int(row.get("revision") or 0)
            derived_from, source_ids = evidence.get(revision, ([], []))
            payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
            revisions.append({
                "revision": revision,
                "at": str(row.get("at") or ""),
                "op": str(row.get("op") or ""),
                "text": str(payload.get("text") or ""),
                "derivedFrom": list(derived_from),
                "sourceIds": list(source_ids),
            })
        return {
            "id": current.header.id,
            "revision": int(current.header.revision),
            "text": str(current.payload.get("text") or ""),
            "revisions": revisions,
        }
