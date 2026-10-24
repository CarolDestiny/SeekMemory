"""确认成功送达后的指定记忆交付；召回和上下文构建不调用本用例。"""

from __future__ import annotations

import datetime
from collections.abc import Iterable, Mapping
from typing import Any

try:
    from ..core.artifact import revise
except ImportError:
    from core.artifact import revise


def confirm_designated_delivery(db: Any, cache: Any, artifact_ids: Iterable[str],
                               *, at: str = "",
                               expected_revisions: Mapping[str, int] | None = None) -> int:
    """按最终正文编号显式写回，失败向调用者传播以保留重试机会。"""
    stamp = at or datetime.datetime.now().isoformat(timespec="seconds")
    written = 0
    for artifact_id in dict.fromkeys(artifact_ids):
        art = db.get(str(artifact_id))
        if art is None or art.header.family != "designated":
            continue
        if art.payload.get("given"):
            if cache is not None:
                cache.put(art)
            continue
        if (expected_revisions is not None
                and expected_revisions.get(art.header.id) != art.header.revision):
            # 送达的是旧版正文；新版仍需保留自己的交付机会。
            continue
        updated = revise(art, payload={**art.payload, "given": stamp})
        db.commit(updated, expected_revision=art.header.revision, op="deliver",
                  reason="designated delivered",
                  source_ids=tuple(art.header.lineage.sources))
        if cache is not None:
            cache.put(updated)
        written += 1
    return written
