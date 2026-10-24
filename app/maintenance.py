"""周期维护用例：自我印象、衰减、合并和人格沉淀的唯一编排。"""

from __future__ import annotations

from typing import Any, Callable


class MemoryMaintenance:
    """Run injected policies in order; persistence and logging stay at their edges."""

    def __init__(
        self, *, self_impressions: Callable[[str], int], decay: Callable[[str], int],
        merge: Callable[[], int], persona: Callable[[str], Any], journal: Any,
    ) -> None:
        self.self_impressions = self_impressions
        self.decay = decay
        self.merge = merge
        self.persona = persona
        self.journal = journal

    def run(self, today: str) -> dict[str, int | bool]:
        """Preserve the maintenance order without importing storage or policy adapters."""
        with self.journal.span("weekly", "self_impression") as metrics:
            made = self.self_impressions(today)
            metrics["made"] = made
        with self.journal.span("weekly", "decay") as metrics:
            dropped = self.decay(today)
            metrics["forgotten"] = dropped
        with self.journal.span("weekly", "merge", threshold=0.6) as metrics:
            merged = self.merge()
            metrics["merged"] = merged
        with self.journal.span("weekly", "persona") as metrics:
            persona = self.persona(today)
            metrics["updated"] = bool(persona)
        self.journal.record(
            "weekly", "info", f"遗忘 {dropped} 条，合并 {merged} 条，人格更新：{bool(persona)}",
        )
        return {"forgotten": dropped, "merged": merged,
                "self_impressions": made, "persona": bool(persona)}
