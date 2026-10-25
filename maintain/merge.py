"""把相似的 scene/detail 合并成 impression 节点，用规则拼出“他经常……”的印象。"""

from __future__ import annotations

import datetime
import re
from collections import Counter

try:  # 作为 astrbot 插件包的一部分导入
    from ..core.artifact import (
        Artifact,
        Lineage,
        Strength,
        TimeSpan,
        content_of,
        make,
        revise,
    )
    from ..store.cache import Cache
    from ..app.ports import ArtifactStore, SourceStore
except ImportError:  # 作为顶层包导入（脚本 / 测试）
    from core.artifact import (
        Artifact,
        Lineage,
        Strength,
        TimeSpan,
        content_of,
        make,
        revise,
    )
    from store.cache import Cache
    from app.ports import ArtifactStore, SourceStore

MAX_ACTIVE = 500
MERGE_LEVELS = ("scene", "detail")


def _clean(text: str) -> str:
    """压缩空白并去掉首尾空格。"""
    return re.sub(r"\s+", " ", text or "").strip()


def _bigrams(text: str) -> set[str]:
    """取规范化字符二元组，作为字面相似度的基础。"""
    plain = re.sub(r"[^\w\u4e00-\u9fff]+", "", text or "").lower()
    if len(plain) < 2:
        return {plain} if plain else set()
    return {plain[i : i + 2] for i in range(len(plain) - 1)}


def _similarity(left: str, right: str) -> float:
    """二元组 Jaccard 相似度，取值 0~1。"""
    a, b = _bigrams(left), _bigrams(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _text_of(art: Artifact) -> str:
    """取节点的可读文本，content_of 不可用时退回 payload["text"]。"""
    try:
        text = content_of(art)
    except Exception:  # noqa: BLE001 - 单个坏节点不能中断整轮合并
        text = ""
    return _clean(text or str(art.payload.get("text") or ""))


def _summarize_texts(texts: list[str]) -> str:
    """用规则把若干场景文本拼成“他经常……”式的印象句。"""
    parts: list[str] = []
    for raw in texts:
        text = _clean(raw).split("。")[0].strip("，,；;、 ")
        text = re.sub(r"^(他|她|你)(经常|总是|老是|一直|常常|平时|最近)?", "", text)
        text = re.sub(
            r"^(今天|昨天|前天|那天|刚才|最近|上周|周末|晚上|早上|中午|下午)",
            "",
            text,
        )
        text = re.sub(r"^(又|总是|老是)", "", text)
        text = text.strip("，,；;、 ")
        text = re.sub(r"[啊呀吧呢哦嘛]+$", "", text)
        if len(text) > 32:
            text = text[:32] + "…"
        if text and text not in parts:
            parts.append(text)
    if not parts:
        return "他经常有些说不上来的习惯，具体是什么，还得再想想。"
    if len(parts) == 1:
        return f"他经常{parts[0]}。"
    if len(parts) == 2:
        return f"他经常{parts[0]}，也常{parts[1]}。"
    return f"他经常{parts[0]}，也常{parts[1]}，偶尔{parts[2]}。"


def _cluster_indices(texts: list[str], threshold: float) -> list[list[int]]:
    """两两比较并把相似文本聚成簇；只返回至少 3 条的簇。"""
    parent = list(range(len(texts)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            if _similarity(texts[i], texts[j]) > threshold:
                root_i, root_j = find(i), find(j)
                if root_i != root_j:
                    parent[root_j] = root_i

    groups: dict[int, list[int]] = {}
    for index in range(len(texts)):
        groups.setdefault(find(index), []).append(index)
    return [indices for indices in groups.values() if len(indices) >= 3]


def _majority(arts: list[Artifact], key: str, default: str) -> str:
    """取 payload 某字段的众数。"""
    values = [
        str(art.payload.get(key))
        for art in arts
        if isinstance(art.payload.get(key), str) and art.payload.get(key)
    ]
    return Counter(values).most_common(1)[0][0] if values else default


def merge_similar(
    artifacts: ArtifactStore, cache: Cache, threshold: float = 0.6, limit: int = 50
) -> int:
    """Merge active scene/detail rows only inside the same subject and scope."""
    pool = [
        art
        for art in list(cache.by_level("scene")) + list(cache.by_level("detail"))
        if art.header.state == "active"
    ]
    if len(pool) <= MAX_ACTIVE:
        return 0

    groups: dict[tuple[str, str], list[Artifact]] = {}
    for art in pool:
        key = (str(art.header.subject_id or ""), str(art.header.scope or "private"))
        groups.setdefault(key, []).append(art)

    now = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M")
    made = 0
    per_group_limit = max(int(limit), 3)
    ordered = sorted(
        groups.values(),
        key=lambda group: min(
            art.header.time.created or art.header.time.updated or "" for art in group
        ),
    )

    for group in ordered:
        group.sort(
            key=lambda art: art.header.time.created or art.header.time.updated or ""
        )
        batch = group[:per_group_limit]
        if len(batch) < 3:
            continue
        texts = [_text_of(art) for art in batch]
        clusters = _cluster_indices(texts, threshold)
        for indices in clusters:
            members = [batch[index] for index in indices]
            strengths = [art.header.strength for art in members]
            count = len(members)
            payload = {
                "text": _summarize_texts([texts[index] for index in indices]),
                "level": "impression",
                "shape": "pattern",
                "chrono": "once",
                "about": _majority(members, "about", "other"),
                "first": False,
            }
            owner_umo = _majority(members, "owner_umo", "")
            if owner_umo:
                payload["owner_umo"] = owner_umo
            sources = tuple(
                dict.fromkeys(
                    source for art in members for source in art.header.lineage.sources
                )
            )
            art = make(
                "memory",
                payload,
                scope=members[0].header.scope,
                strength=Strength(
                    weight=max(item.weight for item in strengths) * 1.2,
                    confidence=max(item.confidence for item in strengths),
                    arousal=sum(item.arousal for item in strengths) / count,
                    valence=sum(item.valence for item in strengths) / count,
                    funny=sum(item.funny for item in strengths) / count,
                ),
                lineage=Lineage(
                    sources=sources,
                    derived_from=tuple(member.header.id for member in members),
                ),
                time=TimeSpan(created=now, updated=now),
                said_by="inferred",
                subject_id=str(members[0].header.subject_id or ""),
            )
            writes = [(art, 0, sources)]
            for member in members:
                writes.append((
                    revise(member, state="merged"),
                    member.header.revision,
                    tuple(member.header.lineage.sources),
                ))
            artifacts.commit_many(
                writes,
                op="merge",
                reason=f"merge {count} memories into impression",
            )
            cache.put(art)
            for member in members:
                cache.remove(member.header.id)
            made += 1
    return made
