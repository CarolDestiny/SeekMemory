"""Memory maintenance: decay, merge, impression and persona evolution."""

from __future__ import annotations

import datetime
from typing import Callable


class MaintenanceService:
    """Own the weekly memory-maintenance pipeline."""

    def __init__(self, *, db, cache, journal, task_id: Callable[[], str], logger) -> None:
        self.db = db
        self.cache = cache
        self.journal = journal
        self.task_id = task_id
        self.logger = logger

    async def weekly(self) -> dict:
        try:
            from ..maintain.decay import decay_all
            from ..maintain.merge import merge_similar
            from ..maintain.persona import distill_self_persona
            from ..maintain.self_impression import build_self_impressions
        except ImportError:
            from maintain.decay import decay_all
            from maintain.merge import merge_similar
            from maintain.persona import distill_self_persona
            from maintain.self_impression import build_self_impressions

        if self.db is None or self.cache is None:
            return {}
        today = datetime.date.today().isoformat()
        with self.journal.span("weekly", "self_impression") as metrics:
            self_made = build_self_impressions(self.db, self.cache, today=today)
            metrics["made"] = self_made
        with self.journal.span("weekly", "decay") as metrics:
            dropped = decay_all(self.db, self.cache, today)
            metrics["forgotten"] = dropped
        with self.journal.span("weekly", "merge", threshold=0.6) as metrics:
            merged = merge_similar(self.db, self.cache, threshold=0.6)
            metrics["merged"] = merged
        with self.journal.span("weekly", "persona") as metrics:
            persona = distill_self_persona(self.db, self.cache, today)
            metrics["updated"] = bool(persona)
        self.journal.record(
            "weekly",
            "info",
            f"forgot {dropped}, merged {merged}, persona updated: {bool(persona)}",
            self.task_id(),
        )
        self.logger.info(
            f"[seekmemory] weekly maintenance: forgot {dropped}, "
            f"merged {merged}, persona {'updated' if persona else 'unchanged'}"
        )
        return {
            "forgotten": dropped,
            "merged": merged,
            "self_impressions": self_made,
            "persona": bool(persona),
        }
