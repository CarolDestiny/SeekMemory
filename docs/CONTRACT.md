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

## 发布契约

发布边界：`scripts/package_plugin.py` 仅接收已构建的生产视图和 Git 跟踪的后端运行文件，
输出根目录可安装的 ZIP 与 SHA-256 校验文件。缺失 SQL、入口、JS/CSS 或许可证即失败；
指定发布标签时必须与 metadata 版本一致。测试、Mock、源码映射、依赖目录和本地数据不得入包。
源码下载保持原样，安装使用 Release 附件，详见 [发布流程](../CONTRIBUTING.md#release-packaging)。

## WebUI 管理接口

宿主扫描 `pages/memory/index.html`，注入 `window.AstrBotPluginPage`。
前端调用 `apiGet("manage/records")` 等相对 endpoint；宿主转发至插件注册的
`/astrbot_plugin_seekmemory/manage/<action>`，并注入管理员请求上下文。
接口拒绝没有 `request.username` 的调用。POST 请求体上限 64 KiB。

| 方法与 action | 输入 | 输出 / 行为 |
|---|---|---|
| GET records | 无 | `{records}`：六个家族、三种状态/scope，完整管理目录 |
| GET detail | query `id` | `{artifact, versions, sources, ledger}`，包含原始快照和证据 |
| GET status | 无 | `{ready, checks, activeTask, pending, pendingTopics, extractionPolicy, checkpointPending, schedulerCount, config}` |
| GET events | 可选 kind/status/search | `{events, capacity:500}`，新事件在前 |
| POST update | id/expectedRevision/payload/scope/state/reason/confirmed | `{id}`，追加修订；禁止更改来源或任意头字段 |
| POST diagnose | query/umo/speaker | `{block, info, visible, excluded}`；无数据库写入 |
| POST task | kind=`extract` 或 `weekly`，confirmed=true | `{id}` 任务 ID；忙时 409 |
| POST cancel | id，confirmed=true | `{id}`；仅取消当前匹配的活动任务 |

update 拒绝多余字段，reason 为 1–300 字符，payload 为对象且序列化长度不超过 50,000，
使用原有 family 校验器，统一调用上游 `DB.commit()`，通过 expected_revision 检测版本冲突。
版本、版本级证据和账本在同一事务内提交，失败整体回滚；成功后更新 Cache。
遗忘使用 `forget`，其他人工修订（含恢复）使用 `revise`；账本 before_hash/after_hash
沿用上游语义，记录修订号字符串。内容哈希从版本的 blob 字段查看。
detail 从 artifact_versions 读取历史，联合旧 evidence 和新版 artifact_evidence 读取来源。
detail 的 header 可选包含 subject_id、said_by 和 time；前端保留缺失字段，不推断旧记录归属。
detail 不补造旧数据缺失的证据或账本；catalog 当前加载完整目录后由前端分页，不提供大库流式加载。

无认证 401，方法错误 405，记录不存在 404，输入错误 400，版本冲突/任务繁忙 409，
引擎不可用 503，未预期异常 500。诊断调用 `build_block(..., dry_run=True)`，跳过 designated 的 mark_given。
模型检测失败仍返回其他检测结果；错误只记录类型，不把异常内容泄漏到生命周期日志。

`webui/service.py` 无宿主依赖；`routes.py` 负责宿主适配；`jobs.py` 管理单一活动任务；
`journal.py` 管理有界持久化日志。每条新事件包含 `level`、`stage`、
`source:{module,file,function,line}`、`context`、`durationMs` 和可空的 `error:{type,frames}`。
`file` 为插件相对路径，外部依赖仅显示文件名；异常帧不含源码正文、局部变量或异常消息。
旧记录缺少字段时前端保留兼容默认值，位置显示“旧记录未采集源码位置”，不会伪造位置信息。
`context` 仅接受显式传入的标量计数或 ID，最多 32 项，字符串截断为 200 字符。
前端支持级别、模块、业务类型和状态组合筛选，文本搜索覆盖函数、行号、阶段、业务字段和任务 ID。

`Journal.span(kind, stage, **context)` 记录阶段起止、耗时、失败或取消，并原样抛出异常。
`Jobs` 使用实例内 ContextVar 传递任务 ID，结束后 reset，避免并发诊断请求误挂在维护任务上。
重启恢复只根据无 stage 的任务生命周期事件判定终态；中间阶段成功不代表整个任务成功。
抽取通过注入的 context-manager 回调记录 provider.call、response.parse、memory.deduplicate、
artifact.validate、artifact.persist 和 impression.revise，不导入 WebUI 或宿主模块。
缓冲沿用上游 `DialogueTurn` 与话题划分；status 同时返回会话汇总和话题摘要（ID、会话、条数、最早时间），不包含对话正文。
extractionPolicy 返回后端采用的积压阈值、TTL 秒数与批次话题上限；checkpointPending 为待强化记忆数，未初始化为 null。
话题全部时间无效时 oldestAt 为 null。日志记录 topic.extract 与话题 ID。
抽取返回上游 `WriteOutcome`，阶段日志记录 written/skipped；模型失败保留会话缓冲。
没有可用模型不消耗批次次数；单个会话失败后继续其他可用会话，批次结束再传播首个失败。
成功后才移除该会话快照中的消息，保留取消、失败以及调用期间新增的消息。
checkpoint 沿用上游同一事务提交修订和 state_events，管理诊断沿用上游检索与 disclosure 判定。
前端模型、hooks、views、宿主适配和组件适配的边界由 Oxlint 约束。
机器可读契约以根目录 [`openapi.yaml`](../openapi.yaml) 为准，描述八个管理操作、请求、成功数据与错误结构。
`dashboard/src/contracts/generated.ts` 由 `pnpm generate:api` 生成，不手工修改。
`ApiRequest` / `ApiResponse` 直接引用生成的 operation 类型；Zod 用 `satisfies` 检查传输兼容性，
并继续处理未知输入、旧日志默认值、深层只读和版本一致性等领域约束。
JSON 扩展内容在生成类型中使用 `unknown`，运行时再由 Zod 递归校验，不使用 `any`。
生成类型不会代替运行校验，也不替换 `ManagementClient` 注入接口或宿主桥接器。

`tests/test_api_contract.py` 校验真实路由/业务输出并导出临时样本；前端跨语言测试用同一 YAML 和 Zod 双重验证。
Mock 返回值也对照 YAML 校验。契约未同步生成类型、实现输出不符、样本缺失或操作覆盖不全都会使 CI 失败。
宿主集成测试在 AstrBot 可用时另行校验真实响应；独立 CI 不依赖宿主启动。
完整开发命令见 [前端工程说明](../dashboard/README.md#接口契约与类型生成)。

## 全局约束

1. 单文件 ≤ 300 行，尽量 150
2. `core/` `store/` `recall/` 不 import `astrbot`
3. 只有 `store/db.py` 写 SQL
4. 所有函数带类型标注
5. 每个文件头部有 docstring：职责一句话
