"""Memory read-path assembly."""

from __future__ import annotations

from typing import Any, Callable

try:
    from ..recall.pipeline import build_block
except ImportError:
    from recall.pipeline import build_block


class RecallService:
    """Build one recall block from the memory stores.

    Capacity pressure is an input, not a second policy owner: the caller passes
    ``degraded`` when the capacity governor has requested smaller recall.
    """

    def __init__(
        self,
        *,
        cache,
        graph,
        db,
        budget,
        config: Callable[[str, Any], Any],
        owner_umo: Callable[[], str],
        hybrid_retriever=None,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.cache = cache
        self.graph = graph
        self.db = db
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
    ) -> tuple[str, dict]:
        """Return the recalled text and its content-free recall metadata."""
        budget_chars = int(self.budget.injection_chars)
        recall_k = int(self.config("recall_k", 8))
        if degraded:
            budget_chars = max(80, budget_chars // 2)
            recall_k = max(1, recall_k // 2)

        def conf(key: str, default):
            if key == "budget_chars":
                return budget_chars
            if key == "recall_k":
                return recall_k
            return self.config(key, default)

        return build_block(
            self.cache,
            self.graph,
            self.db,
            session_id,
            text,
            private,
            conf,
            self.owner_umo(),
            speaker,
            log=self.log,
            hybrid_retriever=self.hybrid_retriever,
        )
