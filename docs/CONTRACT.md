# 模块接口契约

**所有 subagent 必须严格按这里的签名实现，不要改。**

---

## core/artifact.py

```python
from dataclasses import dataclass, field
from typing import Any

@dataclass(frozen=True)
class Strength:
    weight: float = 1.0
    confidence: float = 1.0
    arousal: float = 0.3
    valence: float = 0.0
    funny: float = 0.0

@dataclass(frozen=True)
class TimeSpan:
    created: str = ""
    updated: str = ""
    valid_from: str | None = None
    valid_to: str | None = None
    expires: str | None = None

@dataclass(frozen=True)
class Lineage:
    sources: tuple[str, ...] = ()
    derived_from: tuple[str, ...] = ()

@dataclass(frozen=True)
class Header:
    id: str
    family: str
    revision: int = 1
    state: str = "active"
    scope: str = "private"
    lineage: Lineage = field(default_factory=Lineage)
    strength: Strength = field(default_factory=Strength)
    time: TimeSpan = field(default_factory=TimeSpan)
    said_by: str = "owner"
    shareable: str = "private_only"

@dataclass(frozen=True)
class Artifact:
    header: Header
    payload: dict[str, Any]

def make(family: str, payload: dict, **header_kw) -> Artifact: ...
def revise(art: Artifact, payload: dict | None = None, **header_kw) -> Artifact: ...
def validate(art: Artifact) -> None: ...   # 抛 ValueError
def content_of(art: Artifact) -> str: ...  # 各 family 的"可读文本"
```

## core/strength.py

```python
def retention(s: Strength, shape: str, days: float) -> float: ...
    # 艾宾浩斯 × 形状系数 × 情绪系数
def decayed_weight(s: Strength, shape: str, days: float) -> float: ...
def reinforce(s: Strength, source: str) -> Strength: ...
    # source: "recall"(+0.1) | "spoken"(+0.3) | "confirmed"(+0.2)
def hit_cooldown_ok(last_window: str | None, now: str) -> bool: ...
    # 30 分钟窗口合并
```

## core/tree.py

```python
class Tree:
    def __init__(self, db, cache): ...
    def children(self, node_id: str) -> list[Artifact]: ...
    def impressions(self) -> list[Artifact]: ...
    def add_under(self, child: Artifact, parent_id: str | None) -> Artifact: ...
```

## core/graph.py

```python
class Graph:
    def __init__(self, db, cache): ...
    def link(self, src: str, dst: str, kind: str, weight: float) -> None: ...
    def link_causal(self, src: str, dst: str, weight: float = 1.0) -> None: ...  # 仅接口，不自动调用
    def degree(self, node_id: str) -> int: ...
    def neighbours(self, node_id: str, kinds: tuple[str, ...] = ("similar","causal","temporal")) -> list[tuple[str, float]]: ...
```

## store/db.py

```python
class DB:
    def __init__(self, path: str): ...
    def upsert(self, art: Artifact) -> None: ...
    def get(self, node_id: str) -> Artifact | None: ...
    def list(self, family: str | None = None, state: str | None = None) -> list[Artifact]: ...
    def source_umo(self, source_id: str) -> str: ...
    def add_edge(self, src: str, dst: str, kind: str, weight: float) -> None: ...
    def edges_of(self, node_id: str) -> list[tuple[str, str, float]]: ...
    def add_source(self, sid: str, umo: str, at: str, role: str, text: str, flags: dict) -> None: ...
    def link_evidence(self, node_id: str, source_id: str) -> None: ...
    def ledger_last_hash(self) -> str: ...
    def ledger_append(self, op: str, entity: str, before: str|None, after: str|None, reason: str) -> None: ...
    def count(self, family: str | None = None) -> int: ...
    def close(self) -> None: ...
```

## store/cache.py

```python
class Cache:
    def __init__(self, db: DB): ...
    def load(self) -> None: ...          # 全量载入 active
    def put(self, art: Artifact) -> None: ...
    def get(self, node_id: str) -> Artifact | None: ...
    def active(self, family: str | None = None) -> list[Artifact]: ...
    def by_level(self, level: str) -> list[Artifact]: ...
    def remove(self, node_id: str) -> None: ...
```

## recall/seed.py

```python
def seeds(text: str, pool: list[Artifact], limit: int = 5) -> list[str]: ...
```

## recall/spread.py

```python
def activate(seed_ids: list[str], graph: Graph, cache: Cache, rounds: int = 2) -> dict[str, float]: ...
```

## recall/score.py

```python
def score(art: Artifact, text: str, activation: float, now_days: float) -> float: ...
def select(candidates: list[Artifact] | list[tuple[Artifact, float]],
           text: str, now_days: float, k: int = 8, explore: float = 0.1,
           seed: int | str | None = None, gate: bool = True,
           min_ev_abs: float = 0.5, min_ev_rel: float = 0.3) -> list[Artifact]: ...
def pinned(cache: Cache) -> list[Artifact]: ...   # recall/gate.py
```

`gate=True` 时只保留相关性证据（字面 + 标签 + 情绪 + 激活）达到
`max(min_ev_abs, top_evidence × min_ev_rel)` 的候选，没有候选达标就返回 `[]`；
`weight` / `freshness` 只参与排序。纯问时间的时钟类消息直接返回 `[]`。
`gate=False` 保持旧的 top-k 行为。`pinned(cache)` 返回常驻层
（active persona 全部 + 印象层按 weight 前 2），该层不经过证据闸门。

## recall/scope.py

```python
def owner_of(art: Artifact, lookup: Callable[[str], str] | None = None) -> str: ...
def visible(pool: Iterable[Artifact], umo: str, owner_umo: str = "",
            lookup: Callable[[str], str] | None = None) -> list[Artifact]: ...
```

## recall/designated.py

```python
def triggers_of(art: Artifact) -> list[str]: ...
def matches(art: Artifact, text: str) -> bool: ...
def already_given(art: Artifact) -> bool: ...
def is_private(event) -> bool: ...
def deliverable(art: Artifact, text: str, private: bool) -> bool: ...
def mark_given(db, cache, arts: list[Artifact], block: str, now: str | None = None) -> int: ...
```

## recall/assemble.py

```python
def build(arts: list[Artifact], budget: int = 2000,
          *, text: str | None = None, is_private: bool | None = None) -> str: ...
```

`text` / `is_private` 是新增的**可选**会话上下文，旧调用不受影响：传入后
`designated` 才可能交付正文（私聊 + 命中触发词 + 未 given）；不传时维持
“只给托付提示”。`scope=shadow` 无论是否传上下文都只输出影子句。

## maintain/decay.py

```python
def decay_all(db: DB, cache: Cache, today: str) -> int: ...  # 返回被标 forgotten 的数量
```

## maintain/merge.py

```python
def merge_similar(db: DB, cache: Cache, threshold: float = 0.6, limit: int = 50) -> int: ...
```

## maintain/promote.py

```python
def promote_candidates(cache: Cache, min_hits: int = 3,
                       today: str | None = None) -> list[Artifact]: ...
    # active + level=impression + weight>=1.5 + (hits>=min_hits 或 age>=30 天)
```

## maintain/link.py

```python
def link_new(art: Artifact, graph: Graph | None, cache: Cache | None,
             created: str | None = None) -> int: ...
def persist(art: Artifact, db: DB, cache: Cache | None,
            graph: Graph | None) -> int: ...
    # 先写库/缓存，再建 similar/temporal；建边失败返回 0，不影响写入
```

## maintain/persona.py

```python
def compose(impressions: list[Artifact]) -> str: ...
def distill_persona(db: DB, cache: Cache, today: str | None = None) -> Artifact | None: ...
    # 取 top3 impression 拼第二人称 persona；旧 persona 置 merged，写 merge 账本
```

## maintain/reflect.py

```python
def signals(prev_user: str, cur_user: str) -> dict: ...
    # {"wrong": int, "right": int, "reasons": [...]}
```

---

## 全局约束

1. 单文件 ≤ 300 行，尽量 150
2. `core/` `store/` `recall/` 不 import `astrbot`
3. 只有 `store/db.py` 写 SQL
4. 所有函数带类型标注
5. 每个文件头部有 docstring：职责一句话


---

# v0.3.1 implemented contracts

These contracts are additive to the earlier document.

## core/source.py

```python
@dataclass(frozen=True)
class Source:
    id: str
    turn_id: str
    session_id: str
    speaker_id: str
    role: str
    text: str
    at: str = ""
    reply_to: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

def make_source_id(*, event_id: str = "", session_id: str, speaker_id: str,
                   role: str, text: str, at: str = "") -> str: ...
```

Source is append-only. Both user and assistant messages are Source rows.

## app/contracts.py

```python
@dataclass(frozen=True)
class DialogueTurn:
    session_id: str
    speaker_id: str
    role: str
    text: str
    at: str = ""
    source_id: str = ""
    topic_id: str = ""

@dataclass(frozen=True)
class WriteOutcome:
    written: int = 0
    skipped: int = 0
    ids: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    model_failed: bool = False
```

## core/retrieval.py

```python
@dataclass(frozen=True)
class RetrievalCandidate:
    artifact: Artifact
    activation: float = 0.0
    lexical: float = 0.0
```

`lexical` is reserved for normalized BM25 or another pluggable lexical retriever.

## store/db.py

```python
def append_sources(self, sources: list[Source]) -> int: ...
def source_umos(self, source_ids: list[str]) -> dict[str, str]: ...
def commit(self, art: Artifact, *, expected_revision: int, op: str,
           reason: str = "", source_ids: tuple[str, ...] = (),
           state_events: tuple[StateEvent, ...] = ()) -> None: ...
def history(self, node_id: str) -> list[dict]: ...
```

commit is atomic across node head, append-only version, evidence, state events and ledger.

## app/checkpoint.py

```python
class CheckpointManager:
    def record(self, art: Artifact, at: str = "") -> None: ...
    def flush(self, now: str = "") -> int: ...
    def due(self) -> bool: ...
```

Checkpoint commits the revision and its StateEvent in one transaction.

## core/disclosure.py

```python
@dataclass(frozen=True)
class RecallScene:
    session_id: str
    speaker_id: str
    owner_id: str = ""
    present_ids: tuple[str, ...] = ()

def decide(art: Artifact, scene: RecallScene, relevance: float,
           origin_sessions: Iterable[str] = ()) -> DisclosureDecision: ...
def safe_text(art: Artifact, level: DisclosureLevel) -> str: ...
```

Levels are full, paraphrase, hint and silence. Cross-session content never receives raw text.

## recall/retriever.py

```python
class GraphRetriever:
    def retrieve(self, query: str, pool: list[Artifact]) -> list[RetrievalCandidate]: ...
```

A future BM25 retriever implements the same candidate contract.
