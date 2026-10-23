"""每周人格沉淀：把稳定的 impression 规则拼装成一条 persona（不调模型）。

输入是 ``promote_candidates`` 选出的 impression（weight ≥ 1.5，且
hits ≥ 3 或存在 ≥ 30 天）。输出是一条 family=persona 的 artifact，
旧 persona 标 ``merged``，新 persona 用 ``lineage.derived_from`` 指向
被合并的 impression；每次更新都写 ledger（op="merge"）。
"""

from __future__ import annotations

import re

try:  # 作为 astrbot 插件包的一部分导入
    from ..core.artifact import (
        Artifact,
        Lineage,
        Strength,
        content_of,
        make,
        revise,
    )
    from ..store.cache import Cache
    from ..store.db import DB
    from .promote import promote_candidates
except ImportError:  # 作为顶层包导入（脚本 / 测试）
    from core.artifact import Artifact, Lineage, Strength, content_of, make, revise
    from store.cache import Cache
    from store.db import DB
    from maintain.promote import promote_candidates

TOP_N = 3
_VERBS = ("你记得", "你知道", "你看得出")
_CLEAN = re.compile(r"\s+")


def _clean(text: object) -> str:
    """压平空白并去掉句末标点，供拼装统一加句号。"""
    return _CLEAN.sub(" ", str(text or "")).strip().strip("。！？!?；;，,、 ")


def _text_of(art: Artifact) -> str:
    """取 impression 的可读文本；坏节点回退 payload["text"]。"""
    try:
        text = content_of(art)
    except Exception:  # noqa: BLE001 - 单条坏印象不能拖垮整次沉淀
        text = ""
    return _clean(text or art.payload.get("text"))


def _direct(text: str) -> str:
    """把最高权重的印象改写成直接自述：「他有点倔」→「你有点倔」。"""
    text = re.sub(
        r"^(他们|她们|他|她)(经常|总是|老是|一直|常常|平时|最近)?", "你", text
    )
    if not text.startswith("你"):
        text = "你" + text
    return text + "。"


def compose(impressions: list[Artifact]) -> str:
    """按权重顺序拼成第二人称人格文本；最多取 TOP_N 条，空文本跳过。"""
    parts: list[str] = []
    for index, art in enumerate(impressions[:TOP_N]):
        text = _text_of(art)
        if not text:
            continue
        if not parts:
            parts.append(_direct(text))
        else:
            verb = _VERBS[min(index - 1, len(_VERBS) - 1)]
            parts.append(f"{verb}{text}。")
    return "".join(parts)


def _scope(impressions: list[Artifact]) -> str:
    """全部来源都是 shared 时才共享，否则保持 private。"""
    return "shared" if all(a.header.scope == "shared" for a in impressions) else "private"


def _strength(impressions: list[Artifact]) -> Strength:
    """新 persona 的强度取来源里最高的 weight 与 confidence。"""
    return Strength(
        weight=max(float(a.header.strength.weight) for a in impressions),
        confidence=max(float(a.header.strength.confidence) for a in impressions),
        hits=sum(int(getattr(a.header.strength, "hits", 0) or 0) for a in impressions),
    )


def _sources(impressions: list[Artifact]) -> tuple[str, ...]:
    """合并来源的 lineage.sources，去重且保持首次出现顺序。"""
    return tuple(
        dict.fromkeys(
            source for art in impressions for source in art.header.lineage.sources
        )
    )


def _distill_candidates(
    db: DB,
    cache: Cache,
    impressions: list[Artifact],
) -> Artifact | None:
    """Compose one stable persona from supplied candidates."""
    if not impressions:
        return None
    text = compose(impressions)
    if not text:
        return None

    old = list(cache.active("persona"))
    base = max(old, key=lambda art: art.header.revision) if old else None
    if base is not None and str(base.payload.get("text") or "") == text:
        return base

    chosen = impressions[:TOP_N]
    lineage = Lineage(
        sources=_sources(chosen),
        derived_from=tuple(art.header.id for art in chosen),
    )
    if base is not None:
        persona = revise(
            base,
            payload={"text": text},
            scope=_scope(chosen),
            strength=_strength(chosen),
            lineage=lineage,
            said_by="inferred",
        )
        db.commit(persona, expected_revision=base.header.revision, op="promote",
                  reason="persona revised", source_ids=_sources(chosen))
    else:
        persona = make(
            "persona",
            {"text": text},
            scope=_scope(chosen),
            strength=_strength(chosen),
            lineage=lineage,
            said_by="inferred",
        )
        db.commit(persona, expected_revision=0, op="promote",
                  reason="persona created", source_ids=_sources(chosen))
    cache.put(persona)
    for previous in old:
        if previous.header.id == persona.header.id:
            continue
        merged = revise(previous, state="merged")
        db.commit(merged, expected_revision=previous.header.revision, op="merge",
                  reason=f"merged into {persona.header.id}",
                  source_ids=tuple(previous.header.lineage.sources))
        cache.remove(previous.header.id)
    return persona


def distill_persona(
    db: DB,
    cache: Cache,
    today: str | None = None,
    only_umo: str = "",
) -> Artifact | None:
    """Legacy per-user impression path, kept for compatibility tests."""
    return _distill_candidates(
        db, cache, promote_candidates(cache, today=today, only_umo=only_umo)
    )


def distill_self_persona(
    db: DB,
    cache: Cache,
    today: str | None = None,
) -> Artifact | None:
    """Compose persona only from bot:self self-impressions."""
    from .self_impression import promote_self_candidates

    return _distill_candidates(db, cache, promote_self_candidates(cache, today))
