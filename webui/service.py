"""Framework-independent artifact inspection, revision, and recall diagnostics."""

from __future__ import annotations

import dataclasses
import datetime
import json

try:
    from ..core.artifact import Artifact, content_of, revise, validate
    from ..core.graph import Graph
    from ..recall.pipeline import Conf, build_block
    from ..recall.scope import owner_of, visible
    from ..store.cache import Cache
    from ..store.db import DB
except ImportError:
    from core.artifact import Artifact, content_of, revise, validate
    from core.graph import Graph
    from recall.pipeline import Conf, build_block
    from recall.scope import owner_of, visible
    from store.cache import Cache
    from store.db import DB


def timestamp(value: str) -> str:
    """Normalize legacy local timestamps for the frontend.

    Args:
        value: ISO date/time stored by the backend.

    Returns:
        An offset-aware ISO timestamp; the epoch denotes unknown legacy time.
    """
    try:
        return datetime.datetime.fromisoformat(value).astimezone().isoformat()
    except ValueError:
        return "1970-01-01T00:00:00+00:00"


class ManagementService:
    """Use the existing storage, cache, and scope rules for administrative actions."""

    def __init__(self, db: DB, cache: Cache, graph: Graph, conf: Conf) -> None:
        self.db, self.cache, self.graph, self.conf = db, cache, graph, conf

    def catalog(self) -> list[dict]:
        """Project every artifact family into the shared memory-library contract.

        Returns:
            Administrative records including all scopes and inactive states.
        """
        records = []
        for art in self.db.list():
            header, payload = art.header, art.payload
            text = content_of(art) or "（空内容）"
            versions = {}
            for version in self.db.history(header.id):
                previous = Artifact(header=header, payload=version["payload"])
                versions[version["revision"]] = {
                    "revision": version["revision"],
                    "at": timestamp(version["at"]),
                    "text": content_of(previous) or "（空内容）",
                }
            versions[header.revision] = {
                "revision": header.revision,
                "at": timestamp(header.time.updated),
                "text": text,
            }
            category = (
                payload.get("level", "detail")
                if header.family == "memory"
                else header.family
            )
            tags = payload.get("tags", [])
            if isinstance(tags, str):
                tags = tags.split()
            records.append(
                {
                    "id": header.id,
                    "title": text[:60],
                    "text": text,
                    "category": category,
                    "state": header.state,
                    "scope": header.scope,
                    "subject": str(
                        payload.get("subject") or header.said_by or "unknown"
                    ),
                    "session": owner_of(art, self.db.source_umo) or "未标注会话",
                    "tags": [str(tag) for tag in tags if str(tag)]
                    if isinstance(tags, list)
                    else [],
                    "confidence": max(0, min(1, header.strength.confidence)),
                    "hits": max(0, header.strength.hits),
                    "updatedAt": timestamp(header.time.updated),
                    "versions": sorted(
                        versions.values(),
                        key=lambda item: item["revision"],
                        reverse=True,
                    ),
                    "relatedIds": list(
                        dict.fromkeys(edge[0] for edge in self.db.edges_of(header.id))
                    ),
                }
            )
        return records

    def detail(self, node_id: str) -> dict:
        """Inspect raw payload, headers, evidence, version hashes and ledger.

        Args:
            node_id: Artifact to inspect.

        Returns:
            Administrative detail with no fabricated missing history.

        Raises:
            LookupError: If the artifact no longer exists.
        """
        art = self.db.get(node_id)
        if art is None:
            raise LookupError("Artifact not found")
        return {
            "artifact": dataclasses.asdict(art),
            **self.db.inspect_record(node_id),
            "ledger": [
                dict(row)
                for row in self.db.ledger_entries()
                if row["entity"] == node_id
            ],
        }

    def update(self, body: dict) -> str:
        """Validate and atomically revise an artifact, then refresh its cache.

        Args:
            body: Editor command with ID, expected revision, payload, scope, state and reason.

        Returns:
            Revised artifact ID.

        Raises:
            ValueError: If input is invalid or the revision is stale.
            LookupError: If the artifact is missing.
        """
        if set(body) != {
            "id",
            "expectedRevision",
            "payload",
            "scope",
            "state",
            "reason",
            "confirmed",
        }:
            raise ValueError("Unexpected editor fields")
        if body["confirmed"] is not True:
            raise ValueError("Confirmation required")
        if type(body["expectedRevision"]) is not int or not isinstance(body["id"], str):
            raise ValueError("Invalid revision or ID")
        if body["scope"] not in ("private", "shared", "shadow") or body[
            "state"
        ] not in ("active", "forgotten", "merged"):
            raise ValueError("Invalid state or scope")
        if (
            not isinstance(body["reason"], str)
            or not 1 <= len(body["reason"].strip()) <= 300
        ):
            raise ValueError("A change reason of 1–300 characters is required")
        if (
            not isinstance(body["payload"], dict)
            or len(json.dumps(body["payload"])) > 50000
        ):
            raise ValueError("Invalid payload")
        art = self.db.get(body["id"])
        if art is None:
            raise LookupError("Artifact not found")
        if art.header.state == "merged" and body["state"] != "merged":
            raise ValueError("Merged records cannot be restored independently")
        if art.header.state != "merged" and body["state"] == "merged":
            raise ValueError("Use maintenance to merge records and preserve lineage")
        replacement = revise(
            art, payload=body["payload"], scope=body["scope"], state=body["state"]
        )
        validate(replacement)
        self.db.apply_revision(
            replacement, body["expectedRevision"], body["reason"].strip()
        )
        self.cache.put(replacement)
        return replacement.header.id

    def diagnose(self, body: dict) -> dict:
        """Preview recall through live rules without consuming designated delivery.

        Args:
            body: Query, exact conversation UMO, and sender identity.

        Returns:
            Injection text, decision counters, and scope candidate/exclusion IDs.

        Raises:
            ValueError: If a diagnostic input is missing or too large.
        """
        for key, maximum in (("query", 4000), ("umo", 500), ("speaker", 200)):
            if (
                not isinstance(body.get(key), str)
                or not 0 < len(body[key].strip()) <= maximum
            ):
                raise ValueError(f"Invalid {key}")
        owner = str(self.conf("owner_umo", ""))
        pool = self.cache.active()
        eligible = visible(pool, body["umo"], owner, self.db.source_umo)
        ids = {art.header.id for art in eligible}
        block, info = build_block(
            self.cache,
            self.graph,
            self.db,
            body["umo"],
            body["query"],
            ":FriendMessage:" in body["umo"],
            self.conf,
            owner,
            body["speaker"],
            dry_run=True,
        )
        return {
            "block": block,
            "info": info,
            "visible": sorted(ids),
            "excluded": [art.header.id for art in pool if art.header.id not in ids],
        }
