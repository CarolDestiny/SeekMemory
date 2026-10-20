"""recall.seed：从用户消息里找到最可能唤起记忆的种子节点。

检索分两步：先用倒排索引（bigram → artifact 下标）把候选压到「至少共享
一个二元组」的范围，再只对候选算精确 Dice 重合度。索引与单条记忆的
派生数据都做进程内缓存；池子长度、对象身份或元素顺序变化时自动重建。
"""

from __future__ import annotations

import re
from collections import OrderedDict, defaultdict

try:  # 作为 astrbot 插件包的一部分导入
    from ..core.artifact import Artifact, content_of
except ImportError:  # 作为顶层 recall 包导入（脚本 / 测试）
    from core.artifact import Artifact, content_of

MEME_WORDS: tuple[str, ...] = ("咕咕嘎嘎", "原神", "鸣潮", "抽象", "哈基米")
MEME_BONUS = 0.75
MEME_BONUS_CAP = 1.5

INDEX_CACHE_LIMIT = 8
ART_CACHE_LIMIT = 20_000

# id(pool) 只有在池子对象活着时才唯一，所以索引缓存持有 pool 强引用。
_INDEX_CACHE: OrderedDict[tuple, tuple[list, dict, dict, list]] = OrderedDict()
_ART_CACHE: OrderedDict[int, tuple[Artifact, frozenset[str], tuple[str, ...]]] = OrderedDict()


_PUNCT = str.maketrans(
    "", "",
    " \t\r\n，。！？；：、,.!?;:'\"()[]{}<>…—-_/\\·“”‘’（）《》【】「」『』",
)


def bigrams(text: str) -> set[str]:
    """把文本归一化成二元组集合：保留字母数字，忽略标点与空白。"""
    # 无标点时 isalnum() 是 C 级判断，可直接省掉逐字符过滤；
    # 有标点时先 translate 再判断，仍非纯字母数字才退回逐字符过滤。
    chars = str(text).lower()
    if not chars.isalnum():
        chars = chars.translate(_PUNCT)
        if not chars.isalnum():
            chars = "".join(c for c in chars if c.isalnum())
    if len(chars) < 2:
        return set(chars)
    return {a + b for a, b in zip(chars, chars[1:])}


def overlap(text: str, content: str) -> float:
    """二元组 Dice 重合度：0 表示无关，1 表示完全重合。"""
    a, b = bigrams(text), bigrams(content)
    if not a or not b:
        return 0.0
    return 2.0 * len(a & b) / (len(a) + len(b))


def dice(grams: frozenset[str] | set[str], total: int,
         other: frozenset[str] | set[str]) -> float:
    """用已算好的二元组集合求 Dice，等价于 overlap 的纯计算部分。"""
    if not grams or not other:
        return 0.0
    return 2.0 * len(grams & other) / (total + len(other))


def tags_of(art: Artifact) -> list[str]:
    """取 artifact 的标签，兼容 list 与逗号/空白分隔的字符串。"""
    raw = art.payload.get("tags") or art.payload.get("tag") or []
    if isinstance(raw, str):
        raw = re.split(r"[\s,，#]+", raw)
    return [str(tag).strip().lower() for tag in raw if str(tag).strip()]


def _content(art: Artifact) -> str:
    """content_of 的 fail-open 包装：坏数据不拖垮整次检索。"""
    try:
        return content_of(art)
    except Exception:
        return str(art.payload.get("text") or "")


def _art_info(art: Artifact) -> tuple[frozenset[str], tuple[str, ...]]:
    """取（并缓存）一条记忆的二元组集合与标签；按对象身份失效。"""
    key = id(art)
    cached = _ART_CACHE.get(key)
    if cached is not None:
        _ART_CACHE.move_to_end(key)
        return cached[1], cached[2]
    grams = frozenset(bigrams(_content(art)))
    try:
        tags = tuple(tags_of(art))
    except Exception:
        tags = ()
    _ART_CACHE[key] = (art, grams, tags)
    if len(_ART_CACHE) > ART_CACHE_LIMIT:
        _ART_CACHE.popitem(last=False)
    return grams, tags


def signals_of(art: Artifact) -> tuple[frozenset[str], tuple[str, ...]]:
    """供 recall.score 复用的派生信号：二元组集合 + 标签元组。"""
    return _art_info(art)


def _pool_fingerprint(pool: list[Artifact]) -> tuple:
    """池子指纹：长度、对象身份、逐元素对象身份，任一变化都会重建。"""
    return (len(pool), id(pool), tuple(id(art) for art in pool))


def _build_index(pool: list[Artifact]) -> tuple[list, dict, dict, list]:
    """为一次池子快照建倒排索引，返回（强引用, bigram 倒排, 标签倒排, 条目）。"""
    postings: defaultdict[str, list[int]] = defaultdict(list)
    tag_postings: defaultdict[str, list[int]] = defaultdict(list)
    items: list[tuple[str, frozenset[str], tuple[str, ...]]] = []
    for index, art in enumerate(pool):
        grams, tags = _art_info(art)
        items.append((art.header.id, grams, tags))
        for gram in grams:
            postings[gram].append(index)
        for tag in tags:
            tag_postings[tag].append(index)
    return (pool, postings, tag_postings, items)


def _index_for(pool: list[Artifact]) -> tuple[list, dict, dict, list]:
    """按池子指纹取索引；未命中时重建并做有界淘汰。"""
    fingerprint = _pool_fingerprint(pool)
    cached = _INDEX_CACHE.get(fingerprint)
    if cached is not None:
        _INDEX_CACHE.move_to_end(fingerprint)
        return cached
    index = _build_index(pool)
    _INDEX_CACHE[fingerprint] = index
    while len(_INDEX_CACHE) > INDEX_CACHE_LIMIT:
        _INDEX_CACHE.popitem(last=False)
    return index


def seeds(text: str, pool: list[Artifact], limit: int = 5) -> list[str]:
    """
    从用户消息里提取种子节点 id。

    先用倒排索引筛出与消息共享至少一个二元组的候选，再对候选算二元组
    重合度；消息命中梗词时，带对应标签的 artifact 额外加分。只返回有
    信号的前 limit 条，排序规则与原实现一致（分数降序、id 升序）。
    """
    if not text or limit <= 0 or not pool:
        return []
    wanted = [word for word in MEME_WORDS if word in text]
    _, postings, tag_postings, items = _index_for(pool)
    grams = frozenset(bigrams(text))
    total = len(grams)
    candidates: set[int] = set()
    for gram in grams:
        hit = postings.get(gram)
        if hit:
            candidates.update(hit)
    for word in wanted:
        for tag, hit in tag_postings.items():
            if word in tag:
                candidates.update(hit)

    ranked: list[tuple[float, str]] = []
    for index in candidates:
        node_id, other, tags = items[index]
        value = dice(grams, total, other) if total and other else 0.0
        if wanted:
            hits = sum(1 for word in wanted if any(word in tag for tag in tags))
            value += min(MEME_BONUS_CAP, hits * MEME_BONUS)
        if value > 0:
            ranked.append((value, node_id))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [node_id for _, node_id in ranked[:limit]]
