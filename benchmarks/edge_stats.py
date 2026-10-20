"""消融基准辅助：统计激活扩散比种子多带出了多少候选。"""

from __future__ import annotations

try:  # 作为仓库脚本导入
    from recall.seed import seeds
    from recall.spread import activate
except ImportError:  # pragma: no cover - 包内导入
    from ..recall.seed import seeds
    from ..recall.spread import activate


def spread_counts(pool: list, graph, cache, queries) -> tuple[int, int]:
    """返回（新增候选总数, 有新增候选的题数）；种子自身不计入。"""
    total = 0
    hit = 0
    for query in queries:
        text = query["q"]
        seed_ids = seeds(text, pool)
        activation = activate(seed_ids, graph, cache)
        new = sum(1 for node_id in activation if node_id not in set(seed_ids))
        total += new
        hit += 1 if new else 0
    return total, hit
