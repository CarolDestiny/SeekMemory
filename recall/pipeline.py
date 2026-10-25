"""读路径：一条消息进来，该不该翻记忆、翻哪几条、怎么拼成一段话。

原来嵌在插件入口里，抽出来是为了让 main.py 只做事件桥接。
全部 fail-open：任何异常都由调用方兜住，返回空串也不影响回复。
"""

from __future__ import annotations

import datetime
from collections.abc import Callable
from typing import Any

try:  # 作为 astrbot 插件包的一部分导入
    from ..app.budget import CHARS_PER_TOKEN, estimate_tokens
    from ..app.ports import ArtifactCache, ArtifactStore, Retriever, SourceStore
    from ..core.disclosure import (
        DisclosureLevel,
        RecallScene,
        decide,
        safe_text,
        scope_prior,
    )
    from ..core.graph import Graph
    from ..core.bot_behavior import trusted_self_persona
    from ..recall.assemble import build_with_meta as assemble_text_meta
    from ..recall.designated import deliverable, mark_given
    from ..recall.drift import best_of as drift_best
    from ..recall.drift import should_drift
    from ..recall.gate import pinned
    from ..recall.history import trajectory
    from ..recall.intent import intent_of, is_profile_recall, is_topic_recall
    from ..recall.retriever import GraphRetriever, HybridRetriever
    from ..recall.scope import visible
    from ..recall.temporal import filter_valid, in_window, query_window
    from ..recall.score import select
    from ..recall.source_context import rank_recent, render_same_session
except ImportError:  # 作为顶层包导入（脚本 / 测试）
    from app.budget import CHARS_PER_TOKEN, estimate_tokens
    from app.ports import ArtifactCache, ArtifactStore, Retriever, SourceStore
    from core.disclosure import (
        DisclosureLevel,
        RecallScene,
        decide,
        safe_text,
        scope_prior,
    )
    from core.graph import Graph
    from core.bot_behavior import trusted_self_persona

    from recall.assemble import build_with_meta as assemble_text_meta
    from recall.designated import deliverable, mark_given
    from recall.drift import best_of as drift_best
    from recall.drift import should_drift
    from recall.gate import pinned
    from recall.history import trajectory
    from recall.intent import intent_of, is_profile_recall, is_topic_recall
    from recall.retriever import GraphRetriever, HybridRetriever
    from recall.scope import visible
    from recall.temporal import filter_valid, in_window, query_window
    from recall.score import select
    from recall.source_context import rank_recent, render_same_session

Conf = Callable[[str, Any], Any]


def _conf_bool(conf: Conf, key: str, default: bool) -> bool:
    value = conf(key, default)
    if isinstance(value, str):
        return value.strip().lower() not in ("", "0", "false", "no", "off")
    return bool(value)


def subject_of(speaker: str, owner_umo: str) -> str:
    """这条消息的说话人是谁：主人还是某个 QQ。印象按这个人来调。"""
    owner_id = str(owner_umo or "").split(":")[-1] if owner_umo else ""
    talker = str(speaker or "")
    if not talker:
        return "owner"
    return "owner" if owner_id and talker == owner_id else talker


def recent_context(pool: list, subject: str, *, profile: bool = False,
                   limit: int = 2) -> list:
    """Return recent global memory for an explicit recall question.

    Subject match is a ranking factor rather than a visibility gate; private
    memory from another conversation can still influence the fallback.
    """
    if not subject:
        return []
    levels = ("fact", "scene", "detail") if profile else ("scene", "detail", "fact")
    rows = []
    for art in pool:
        try:
            if art.header.family != "memory":
                continue
            if str(art.header.scope or "") not in ("shared", "private"):
                continue
            if str(art.payload.get("level") or "") not in levels:
                continue
            subject_id = str(art.header.subject_id or "")
            said_by = str(art.header.said_by or "")
            if subject_id == subject or said_by == subject:
                affinity = 2
            elif subject_id == "owner":
                affinity = 1
            else:
                affinity = 0
            rows.append((affinity, str(art.header.time.created or ""),
                         str(art.header.id), art))
        except Exception:
            continue
    rows.sort(key=lambda row: (row[0], row[1], row[2]), reverse=True)
    return [row[3] for row in rows[:max(0, limit)]]


def build_block(
    cache: ArtifactCache,
    graph: Graph,
    artifacts: ArtifactStore,
    sources: SourceStore,
    umo: str,
    text: str,
    private: bool,
    conf: Conf,
    owner_umo: str,
    speaker: str = "",
    log: Callable[[str], None] = lambda _msg: None,
    *,
    dry_run: bool = False,
    hybrid_retriever: Retriever | None = None,
) -> tuple[str, dict]:
    """按常驻层、检索和偶然浮现组装会话的记忆注入文本。

    Args:
        cache: 运行中的活跃 Artifact 缓存。
        graph: 用于激活扩散的关系图。
        artifacts/sources: repository ports used for ownership and delivery.
        umo: 完整会话标识。
        text: 触发召回的输入消息。
        private: 是否为私聊。
        conf: 与插件共用的带类型配置查询函数。
        owner_umo: 配置中的所有者会话。
        speaker: 实际发送者身份。
        log: 召回摘要回调。
        dry_run: 管理预览时跳过交付状态写入。
        hybrid_retriever: 可选的长生命周期检索器，实现既有 Retriever 协议。

    Returns:
        注入文本与运行决策计数。
    """
    lookup = sources.source_umo
    subject = subject_of(speaker, owner_umo)
    owner_id = str(owner_umo or "").split(":")[-1] if owner_umo else ""
    scene = RecallScene(umo, str(speaker or ""), owner_id, (str(speaker or ""),))
    pinned_arts = visible(pinned(cache, subject), umo, owner_umo, lookup)
    pool = [
        a
        for a in visible(cache.active(), umo, owner_umo, lookup)
        if deliverable(a, text, private)
    ]
    pool = filter_valid(pool)
    window = query_window(text)
    if window is not None:
        pool = [
            art for art in pool
            if art.header.family != "memory" or in_window(art, window)
        ]
    source_enabled = _conf_bool(conf, "source_context_enabled", True)
    if not pool and not pinned_arts and not source_enabled:
        return "", {
            "mode": "none",
            "picked": 0,
            "pinned": 0,
            "chars": 0,
            "picked_ids": (),
            "pinned_ids": (),
            "disclosure": {},
            "fallback": "",
            "candidates": 0,
            "gate": {"evaluated": False, "passed": 0, "rejected": 0, "threshold": 0.0},
        }

    designated = [a for a in pool if a.header.family == "designated"]
    pool = [a for a in pool if a.header.family != "designated"]

    mode = intent_of(text)
    picked: list = []
    candidates: list = []
    gate_info = {"evaluated": False, "passed": 0, "rejected": 0, "threshold": 0.0}
    if mode != "none" and pool:
        lexical_weight = 2.0
        if bool(conf("bm25_enabled", True)):
            retriever = hybrid_retriever or HybridRetriever(graph, cache)
            lexical_weight = float(conf("bm25_weight", 1.0))
        else:
            retriever = GraphRetriever(graph, cache)
        candidates = retriever.retrieve(text, pool)
        candidates = [
            type(candidate)(
                candidate.artifact,
                candidate.activation * scope_prior(candidate.artifact),
                candidate.lexical * scope_prior(candidate.artifact),
            )
            for candidate in candidates
        ]
        loose = mode == "loose"
        picked = select(
            candidates,
            text,
            0.0,
            k=int(conf("recall_k", 8)) + (2 if loose else 0),
            explore=float(conf("explore_rate", 0.1)),
            gate=True,
            min_ev_abs=float(conf("recall_min_ev_abs", 0.5)),
            min_ev_rel=0.2 if loose else float(conf("recall_min_ev_rel", 0.3)),
            lexical_weight=lexical_weight,
            diagnostics=gate_info,
        )

    # 没有线索时也可能突然想起一件事——这不走 query 打分。
    fallback = ""
    if not picked:
        fallback_subject = owner_id if subject == "owner" else subject
        if is_profile_recall(text):
            picked = recent_context(pool, fallback_subject, profile=True)
            fallback = "recent_profile" if picked else ""
        elif is_topic_recall(text):
            picked = recent_context(pool, fallback_subject)
            fallback = "recent_topic" if picked else ""

    if not picked and should_drift(text, seed=text):
        one = drift_best(pool, seed=text)
        if one is not None:
            picked = [one]
            log(f"主动想起：{one.header.id}")

    overrides: dict[str, str] = {}
    disclosure_info: dict[str, str] = {}

    def apply_disclosure(arts: list, relevance: float) -> list:
        safe_arts = []
        for art in arts:
            try:
                if art.header.family == "persona":
                    safe = trusted_self_persona(art)
                    disclosure_info[art.header.id] = "full" if safe else "silence"
                    if safe:
                        safe_arts.append(art)
                    continue
                source_ids = list(art.header.lineage.sources)
                origins = (
                    tuple(sources.source_umos(source_ids).values())
                )
                if art.header.family == "designated":
                    owner_ref = str(
                        art.payload.get("owner_umo")
                        or art.payload.get("owner")
                        or ""
                    )
                    if owner_ref in (umo, owner_umo) or umo in origins:
                        disclosure_info[art.header.id] = "full"
                        safe_arts.append(art)
                    else:
                        disclosure_info[art.header.id] = "silence"
                    continue
                decision = decide(art, scene, relevance, origins)
                disclosure_info[art.header.id] = decision.level.value
                if decision.level == DisclosureLevel.SILENCE:
                    continue
                if decision.level != DisclosureLevel.FULL:
                    safe = safe_text(art, decision.level)
                    if not safe:
                        continue
                    overrides[art.header.id] = safe
                safe_arts.append(art)
            except Exception:
                continue
        return safe_arts

    safe_pinned = apply_disclosure(pinned_arts, 1.0)
    safe_designated = apply_disclosure(designated, 1.0)
    safe_picked = apply_disclosure(
        picked, 1.0 if mode != "none" else 0.5
    )
    picked = safe_picked

    budget = int(conf("budget_chars", 600))
    notes = {}
    for art in safe_pinned + picked:
        try:
            if str(art.payload.get("level") or "") == "impression":
                note = trajectory(cache, art)
                if note:
                    notes[art.header.id] = note
        except Exception:  # noqa: BLE001 - trajectory is optional
            continue
    block, final_ids, dropped_ids = assemble_text_meta(
        safe_pinned + safe_designated + picked,
        budget=int(budget * (1.4 if mode == "loose" else 1.0)),
        text=text,
        is_private=private,
        notes=notes,
        overrides=overrides,
    )
    normal_picked = list(picked)
    source_info: dict[str, Any] | None = None
    if source_enabled:
        source_info = {
            "enabled": True,
            "candidates": 0,
            "artifacts": 0,
            "picked": 0,
            "raw_sources": 0,
            "chars": 0,
            "tokens": 0,
            "protected_sources": 0,
            "fallback": "",
        }
        if not block.strip():
            try:
                hours = max(1, int(conf("source_context_hours", 12)))
                max_sources = max(1, int(conf("source_context_max_sources", 80)))
                since = (
                    datetime.datetime.now() - datetime.timedelta(hours=hours)
                ).isoformat(timespec="seconds")
                recent = sources.recent_sources(since=since, limit=max_sources)
                ranked = rank_recent(
                    text,
                    recent,
                    session_id=umo,
                    speaker=speaker,
                    limit=max_sources,
                )
                source_ids = [item.source.id for item in ranked]
                source_info["candidates"] = len(ranked)
                source_arts = artifacts.by_source_ids(source_ids)
                protected_ids: set[str] = set()
                for art in source_arts:
                    if (
                        str(art.header.family or "") in ("secret", "designated")
                        or str(art.header.scope or "") in ("shadow", "secret")
                        or str(art.header.shareable or "") == "secret"
                    ):
                        protected_ids.update(str(value) for value in art.header.lineage.sources)
                source_info["protected_sources"] = len(protected_ids)
                eligible = [
                    art for art in visible(source_arts, umo, owner_umo, lookup)
                    if deliverable(art, text, private)
                ]
                eligible = filter_valid(eligible)
                if window is not None:
                    eligible = [
                        art for art in eligible
                        if art.header.family != "memory" or in_window(art, window)
                    ]
                fallback_picked = apply_disclosure(eligible, 1.0)
                fallback_block, fallback_final, fallback_dropped = assemble_text_meta(
                    fallback_picked,
                    budget=budget,
                    text=text,
                    is_private=private,
                    notes=notes,
                    overrides=overrides,
                )
                source_info["artifacts"] = len(source_arts)
                source_info["picked"] = len(fallback_picked)
                if fallback_block:
                    block = fallback_block
                    final_ids = fallback_final
                    dropped_ids = fallback_dropped
                    picked = fallback_picked
                    source_info["fallback"] = "artifact"
                    source_info["chars"] = len(fallback_block)
                    source_info["tokens"] = estimate_tokens(len(fallback_block))
                else:
                    source_cap = int(
                        max(0, int(conf("source_context_tokens", 150)))
                        * CHARS_PER_TOKEN
                    )
                    min_free = int(
                        max(0, int(conf("source_context_min_free_tokens", 60)))
                        * CHARS_PER_TOKEN
                    )
                    free = max(0, budget - len(block))
                    if source_cap > 0 and free >= min_free:
                        raw, used = render_same_session(
                            ranked,
                            scene,
                            budget_chars=min(free, source_cap),
                            protected_source_ids=protected_ids,
                        )
                        if raw:
                            block = raw
                            final_ids = ()
                            dropped_ids = ()
                            picked = []
                            source_info["fallback"] = "source"
                            source_info["raw_sources"] = len(used)
                            source_info["chars"] = len(raw)
                            source_info["tokens"] = estimate_tokens(len(raw))
            except Exception as exc:  # noqa: BLE001 - Source fallback is optional
                log(f"source fallback failed: {type(exc).__name__}")
                source_info["error"] = type(exc).__name__
    if not dry_run:
        mark_given(artifacts, cache, safe_designated + picked, block)
    info = {
        "mode": mode,
        "picked": len(picked),
        "pinned": len(safe_pinned),
        "chars": len(block),
        "drift": bool(normal_picked) and not designated,
        "picked_ids": tuple(a.header.id for a in picked),
        "final_ids": final_ids,
        "dropped_ids": dropped_ids,
        "disclosure": disclosure_info,
        "pinned_ids": tuple(a.header.id for a in safe_pinned),
        "fallback": fallback,
        "candidates": len(candidates),
        "gate": gate_info,
    }
    if source_info is not None:
        info["source_context"] = source_info
    return block, info
