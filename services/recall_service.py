"""Memory read-path assembly."""

from __future__ import annotations

from typing import Any, Callable

try:
    from ..app.ports import ArtifactStore, SourceStore
except ImportError:
    from app.ports import ArtifactStore, SourceStore

try:
    from ..recall.designated import deliverable
    from ..recall.pipeline import build_block
    from ..recall.scope import visible
except ImportError:
    from recall.designated import deliverable
    from recall.pipeline import build_block
    from recall.scope import visible


class RecallService:
    """Build one recall block from the memory stores.

    Capacity pressure is an input, not a second policy owner: the caller passes
    ``degraded`` when the capacity governor has requested smaller recall.
    """

    def __init__(
        self,
        *,
        cache: Any,
        graph: Any,
        artifacts: ArtifactStore | None,
        sources: SourceStore | None,
        budget,
        config: Callable[[str, Any], Any],
        owner_umo: Callable[[], str],
        hybrid_retriever=None,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.cache = cache
        self.graph = graph
        self.artifacts = artifacts
        self.sources = sources
        self.budget = budget
        self.config = config
        self.owner_umo = owner_umo
        self.hybrid_retriever = hybrid_retriever
        self.log = log or (lambda _msg: None)

    def build(
        self,
        text: str,
        session_id: str = "",
        private: bool = False,
        speaker: str = "",
        *,
        degraded: bool = False,
        dry_run: bool = False,
    ) -> tuple[str, dict]:
        """Return the recalled text and its content-free recall metadata."""
        budget_chars = int(self.budget.injection_chars)
        recall_k = int(self.config("recall_k", 8))
        if degraded:
            budget_chars = max(80, budget_chars // 2)
            recall_k = max(1, recall_k // 2)

        source_fields = {
            "source_context_enabled",
            "source_context_hours",
            "source_context_max_sources",
            "source_context_tokens",
            "source_context_min_free_tokens",
        }

        def conf(key: str, default):
            if key == "budget_chars":
                return budget_chars
            if key == "recall_k":
                return recall_k
            if key in source_fields:
                value = getattr(self.budget, key, None)
                return self.config(key, default) if value is None else value
            return self.config(key, default)

        return build_block(
            self.cache,
            self.graph,
            self.artifacts,
            self.sources,
            session_id,
            text,
            private,
            conf,
            self.owner_umo(),
            speaker,
            log=self.log,
            dry_run=dry_run,
            hybrid_retriever=self.hybrid_retriever,
        )

    def preview(self, text: str, session_id: str, private: bool,
                speaker: str = "") -> dict:
        """Run the recall path without writing delivery state."""
        block, info = self.build(
            text, session_id, private, speaker, dry_run=True
        )
        owner = self.owner_umo()
        pool = self.cache.active() if self.cache is not None else []
        eligible = visible(pool, session_id, owner, self.sources.source_umo)
        eligible = [
            art for art in eligible if deliverable(art, text, private)
        ]
        ids = {art.header.id for art in eligible}
        return {
            "block": block,
            "info": info,
            "visible": sorted(ids),
            "excluded": [art.header.id for art in pool if art.header.id not in ids],
        }
