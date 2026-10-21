from __future__ import annotations

try:
    from ..core.graph import Graph
    from ..core.retrieval import RetrievalCandidate
    from ..store.cache import Cache
    from .seed import seeds
    from .spread import activate
except ImportError:
    from core.graph import Graph
    from core.retrieval import RetrievalCandidate
    from store.cache import Cache
    from recall.seed import seeds
    from recall.spread import activate


class GraphRetriever:
    def __init__(self, graph: Graph, cache: Cache) -> None:
        self.graph = graph
        self.cache = cache

    def retrieve(self, query: str, pool: list) -> list[RetrievalCandidate]:
        seed_ids = seeds(query, pool)
        activation = activate(seed_ids, self.graph, self.cache)
        return [RetrievalCandidate(art, float(activation.get(art.header.id, 0.0)))
                for art in pool]
