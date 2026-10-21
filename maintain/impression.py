"""印象修订：新证据进来时，改旧印象，而不是再堆一条。

人对一个人的看法是会被改写的：先说"他有点倔"，后来变成"他嘴上不饶人，
但真有事会帮"。机制上就是同一条印象出新 revision，旧 revision 留在账本里。

两类处理：
- 新证据和旧印象几乎同一句话（重合度 ≥ 0.85）：只加一次证据（权重、hits），不造新版本；
- 新证据把旧印象说得更准（重合度 ≥ 0.45）：出 revision +1，正文换成新的，
  权重取两者较高再加一点，旧版本的 id 不变、历史进 blob 与账本。

任何异常都返回 None，不影响已经完成的写入。
"""

from __future__ import annotations

from dataclasses import replace

try:  # 作为 astrbot 插件包的一部分导入
    from ..core.artifact import Artifact, content_of, revise
    from ..store.cache import Cache
    from ..store.db import DB
    from ..recall.seed import overlap
except ImportError:  # 作为顶层包导入（脚本 / 测试）
    from core.artifact import Artifact, content_of, revise
    from store.cache import Cache
    from store.db import DB
    from recall.seed import overlap

LEVEL = "impression"
FAMILY = "memory"
REINFORCE_OVERLAP = 0.85
REVISE_OVERLAP = 0.45
WEIGHT_STEP = 0.1
WEIGHT_CAP = 3.0


def _text(art: Artifact) -> str:
    """取可读文本；坏节点回退 payload["text"]。"""
    try:
        text = content_of(art)
    except Exception:  # noqa: BLE001 - 单条坏印象不拖垮整次修订
        text = ""
    return str(text or art.payload.get("text") or "").strip()


def _rivals(cache: Cache, art: Artifact) -> list[Artifact]:
    """同 scope 的其它 active 印象；不跨 scope 改。"""
    out = []
    for old in cache.active("memory"):
        try:
            if old.header.id == art.header.id:
                continue
            if str(old.payload.get("level") or "") != LEVEL:
                continue
            if old.header.scope != art.header.scope:
                continue
            out.append(old)
        except Exception:  # noqa: BLE001
            continue
    return out


def _best_match(cache: Cache, art: Artifact) -> tuple[Artifact | None, float]:
    """找和新印象最像的旧印象，返回 (旧印象, 重合度)。"""
    text = _text(art)
    if not text:
        return None, 0.0
    best, score = None, 0.0
    for old in _rivals(cache, art):
        try:
            value = overlap(text, _text(old))
        except Exception:  # noqa: BLE001
            continue
        if value > score:
            best, score = old, value
    return best, score


def revise_impression(db: DB, cache: Cache, art: Artifact) -> Artifact | None:
    """把新印象并入旧印象，返回改写后的版本；不需要修订时返回 None。"""
    try:
        if art.header.family != FAMILY:
            return None
        if str(art.payload.get("level") or "") != LEVEL:
            return None
        old, score = _best_match(cache, art)
        if old is None or score < REVISE_OVERLAP:
            return None
        weight = min(WEIGHT_CAP, max(float(old.header.strength.weight),
                                     float(art.header.strength.weight)) + WEIGHT_STEP)
        hits = int(old.header.strength.hits or 0) + 1
        if score >= REINFORCE_OVERLAP:
            return _reinforce(db, cache, old, weight, hits)
        return _reword(db, cache, art, old, weight, hits, score)
    except Exception:  # noqa: BLE001 - 修订失败不能影响写入
        return None


def _reinforce(db: DB, cache: Cache, old: Artifact,
               weight: float, hits: int) -> Artifact:
    """同一句话再出现一次：只加权重与命中数，不产生新版本。"""
    new = revise(old, revision=old.header.revision,
                 strength=replace(old.header.strength, weight=weight, hits=hits))
    db.upsert(new)
    cache.put(new)
    db.ledger_append("reinforce", new.header.id, old.header.id, new.header.id,
                     f"同一印象再次出现，权重 {old.header.strength.weight:.2f}→{weight:.2f}")
    return new


def _reword(db: DB, cache: Cache, art: Artifact, old: Artifact,
            weight: float, hits: int, score: float) -> Artifact:
    """说法变了：出新 revision，正文换成更准的那句。"""
    text = _text(art)
    payload = {**old.payload, **art.payload, "text": text}
    lineage = replace(old.header.lineage,
                      derived_from=tuple(dict.fromkeys(
                          old.header.lineage.derived_from + (old.header.id,))))
    new = revise(
        old,
        payload,
        strength=replace(old.header.strength, weight=weight, hits=hits),
        lineage=lineage,
        scope=art.header.scope,
    )
    db.upsert(new)
    cache.put(new)
    db.ledger_append("merge", new.header.id, old.header.id, new.header.id,
                     f"印象修订（重合 {score:.2f}）：{_text(old)} → {text}")
    return new
