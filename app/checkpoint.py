from __future__ import annotations

import time
from dataclasses import replace

try:
    from ..core.artifact import Artifact, revise
    from ..core.versioning import StateEvent
except ImportError:
    from core.artifact import Artifact, revise
    from core.versioning import StateEvent

MAX_WEIGHT = 3.0


class CheckpointManager:
    def __init__(self, store, cache, interval: int = 1800) -> None:
        self.store = store
        self.cache = cache
        self.interval = max(1, int(interval))
        self.last_flush = time.monotonic()
        self._dirty: dict[str, dict] = {}

    def record(self, art: Artifact, at: str = "") -> None:
        if art.header.id not in self._dirty:
            self._dirty[art.header.id] = {"revision": art.header.revision, "hits": 0}
        self._dirty[art.header.id]["hits"] += 1
        if at:
            self._dirty[art.header.id]["at"] = at

    def due(self) -> bool:
        return bool(self._dirty) and time.monotonic() - self.last_flush >= self.interval

    def pending(self) -> int:
        return len(self._dirty)

    def flush(self, now: str = "") -> int:
        flushed = 0
        for entity, delta in list(self._dirty.items()):
            art = self.cache.get(entity)
            if art is None:
                self._dirty.pop(entity, None)
                continue
            hits = int(delta.get("hits") or 0)
            if hits <= 0:
                self._dirty.pop(entity, None)
                continue
            stamp = now or str(delta.get("at") or "")
            event = StateEvent(
                id=f"ev_{time.time_ns()}_{entity}", entity_id=entity,
                revision_seen=art.header.revision, op="reinforce",
                delta={"hits": hits, "weight": round(0.1 * hits, 6)}, at=stamp)
            old = art.header.strength
            strength = replace(old, hits=int(old.hits or 0) + hits,
                               weight=min(MAX_WEIGHT, float(old.weight) + 0.1 * hits))
            new = revise(art, strength=strength)
            try:
                self.store.append_state_event(event)
                self.store.commit(new, expected_revision=art.header.revision,
                                  op="reinforce", reason="checkpoint",
                                  source_ids=tuple(art.header.lineage.sources))
                self.cache.put(new)
                flushed += 1
            except Exception:
                continue
            self._dirty.pop(entity, None)
        self.last_flush = time.monotonic()
        return flushed
