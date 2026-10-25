# ISSUE-0033: Token control and Source-backed recent context

- Status: in_progress
- Priority: P1
- Owner: application services, with pure policy helpers
- Related: ISSUE-0024 (BM25), ISSUE-0028 (capacity/Source projection), ISSUE-0031 (request context budget)
- Supersedes: none

## Background / Why this issue exists

SeekMemory already has two sources of cost and two gaps in recall:

1. Background extraction has no prompt-size or total-token budget. `MAX_TOPIC_TURNS`
   allows a single extraction call to carry up to 120 dialogue turns, and consecutive
   dream batches can keep issuing model calls without a per-night ceiling. The dream
   ledger currently records batch/write counts but not `usage_in`, `usage_cached`, or
   `usage_out`, so the nightly bill cannot be attributed to extraction.
2. Recall only ranks active Artifacts. In dream mode, recent dialogue can remain as
   immutable Source evidence for many hours before extraction. During that window the
   assistant cannot use recent conversational continuity. Source is also the only
   complete truth, so a retrieval path that can never look at Source is needlessly
   blind when memory extraction lags.

The observed user problem is therefore concrete: a nightly run can exceed the desired
cost budget, while the same run still provides poor recent continuity because its
Source rows are not searchable by recall. Lowering `dream_max_batches` only hides the
symptom; it does not make individual prompts bounded, make usage observable, or make
Source available to recall.

This must be solved now because the next product steps (cross-group recent context,
favorability and proactive speech) all consume the same context and token budget. If
Source retrieval and budget ownership are added later as ad-hoc paths, they will
duplicate recall and bypass disclosure.

## Goals / Scope

- Add bounded Source-backed recall fallback, using recent immutable Sources.
- Keep all group Sources eligible for **evidence discovery**, while raw Source text
  remains origin-scoped and never bypasses the privacy matrix.
- Add explicit token budgets for Source context and background extraction.
- Record actual extraction model usage and include it in the dream summary.
- Keep one recall owner (`RecallService`) and one extraction writer (`IngestService`).

## Non-goals

- No vector database, embedding service, network call, or new model call on the chat
  path.
- No change to Artifact fields, CAS/version/evidence/ledger semantics, or Source truth.
- No raw cross-session Source injection. Cross-group continuity uses derived Artifacts
  and their existing disclosure decisions.
- No favorability, proactive speech, ImportService, persona UI, or new service in
  `ServiceCollection`.
- No automatic schema migration beyond an additive Source-time index.

## Ownership decision

| Semantics | Owner |
|---|---|
| SQL for recent Source rows and Artifact-by-Source lookup | `SourceStore` / `ArtifactStore` repository ports |
| Source candidate ranking, same-session rendering and safe projection | new pure module `recall/source_context.py` |
| Single recall composition and delivery marking | `RecallService` / `recall/pipeline.py` |
| Extraction prompt chunking and usage accumulation | `IngestService` |
| Dream stop condition and summary merge | `DreamCycle` called by `BackgroundService` |
| Budget parsing and token estimation | `app/budget.py` |
| Privacy decision | `core/disclosure.py` for Sources plus existing Artifact disclosure |

No new manager, registry, DI container, database table, or write path.

## Design

### 1. Source-backed recall fallback

The normal Artifact recall runs first. Only when it produces no delivered memory does
the service run a bounded Source fallback. This keeps the common chat path cheap and
avoids turning Source search into a second always-on retrieval hub. The existing early
`mode="none"` return must be moved after this fallback attempt.

```text
RecallService.build()
  -> existing visible Artifact candidates / graph + BM25 / disclosure
  -> if no Artifact was delivered and source_context is enabled:
       SourceStore.recent_sources(since, max_sources)
       recall.source_context.rank_recent(query, sources, session, speaker)
       ArtifactStore.by_source_ids(top_source_ids)
       visible + deliverable + existing disclosure + assemble
  -> if still no Artifact:
       same-session recent Source snippets may fill the remaining injection budget
  -> info includes content-free source-context counters
```

Rules:

- `recent_sources` is bounded by time, row count and session-agnostic global ordering.
- Source ranking is local deterministic BM25 (character bigrams) plus recency and
  same-session/same-speaker bonuses. It performs no model call.
- Source IDs are internal retrieval signals. A Source may lead to an Artifact from a
  different session only through `by_source_ids`; the Artifact then passes the existing
  visibility and disclosure gate.
- Same-session recent Source text may be rendered only after the source-level privacy
  decision returns `full`, clipped to the remaining token budget. Sources whose
  normalized text equals the current query are excluded to avoid echoing the inbound
  message, and only the newest bounded window is considered.
- Raw same-session snippets are additionally excluded when `by_source_ids()` shows
  that the Source backs an active `secret`, `designated` or `shadow` Artifact. Source
  fallback must never become a bypass around the protected Artifact delivery rules.
- Source fallback requires a positive query signal: a non-zero local lexical match or
  an explicit recall intent. Clock-only/empty queries and unrelated small talk do not
  pull in recent Source text.
- The Source fallback never writes Artifact delivery state and never reinforces a
  memory; only assembled Artifact IDs are marked as delivered as before.
- `source_context.enabled=false` restores current behavior exactly.

### 2. Privacy matrix for Sources

The existing `core.disclosure` policy stays the single disclosure owner. Add a pure
Source decision beside it; do not create a second policy object.

| Origin vs current scene | Role | Raw Source allowed? | Effect |
|---|---|---:|---|
| same session | any | yes, clipped | `full` |
| other session; same speaker; current scene private | user | no | `hint` only; may discover Artifacts |
| other session; same speaker; current scene group | user | no | `hint` only; no raw text |
| other session; different speaker | any | no | `silence` for source rendering |
| other session | assistant/system/tool/external | no | `silence` |
| any | secret / designated Artifact | unchanged | existing Artifact disclosure still applies |

Important: cross-group raw text is never copied into another group. Cross-group
continuity is provided by Artifacts whose lineage points at those Sources and by the
existing Artifact disclosure model. `hint` may contribute only a generic continuity
sentence, never source text, names, identifiers or extracted payload fields.

### 3. Request-side token budget

Extend the existing pure `ContextBudget` in `app/budget.py`; do not create a second
budget object for recall.

New values with conservative defaults:

```text
source_context_enabled        = true
source_context_hours          = 12
source_context_max_sources    = 80
source_context_tokens         = 150
source_context_min_free_tokens= 60
```

`context_budget` remains the total injection bound. Source context may use only the
free remainder after the Artifact block. Token limits are converted with
`int(tokens * CHARS_PER_TOKEN)` at the text boundary; `estimate_tokens()` is used only
for reporting. The final prompt text must never exceed `budget_chars`. `info` reports
estimates and counts, never Source text.

### 4. Extraction token budget and usage accounting

Add a separate pure `ExtractionBudget` in `app/budget.py`:

```text
extraction_chunk_tokens = 2400
dream_token_budget       = 60000   # 0 disables the hard dream stop
```

`app/flush_policy.chunk_turns(items, limit=..., max_tokens=...)` remains deterministic
and preserves user/assistant reply pairs. Packing stops before either the turn or token
limit would be exceeded, backs off one row when the boundary would split a user/reply
pair, and emits all remaining turns in later chunks. A single oversized turn is retained
as its own chunk; no input may be silently dropped.

`IngestService`:

- estimates each chunk with `app.budget.estimate_messages`;
- records `usage_in`, `usage_cached`, `usage_out` from each `ChatResponse`;
- exposes a content-free cumulative `usage_snapshot()`;
- returns per-call usage on `WriteOutcome` fields (defaults 0 for compatibility),
  including parse/evidence/partial-commit outcomes reached after a successful model
  call;
- keeps `usage_snapshot()` content-free and exact.

`DreamCycle.run()` accepts an optional `usage` callback. Before each next flush it
compares cumulative input+output tokens with the baseline and `dream_token_budget`.
When the budget is reached it stops submitting new batches but still runs maintenance
for already committed work. It records in `dream_runs.summary`:

```json
{
  "budget": {"tokens": 60000, "used": 53120, "stopped": "token_budget"},
  "usage": {"calls": 12, "in": 42100, "cached": 2000, "out": 11020}
}
```

When `dream_token_budget=0`, stop semantics are unchanged except usage is still recorded.

### 5. SourceStore / ArtifactStore port additions

```python
class SourceStore(Protocol):
    def recent_sources(self, *, since: str, limit: int) -> list[Source]: ...

class ArtifactStore(Protocol):
    def by_source_ids(self, source_ids: list[str]) -> list[Artifact]: ...
```

`SourceRepository.recent_sources` uses indexed `sources.at` ordering. Add
`CREATE INDEX IF NOT EXISTS idx_sources_at ON sources(at)` to `store/schema.sql`.
`ArtifactRepository.by_source_ids` joins `artifact_evidence` to active nodes and
returns active Artifacts. Add an `artifact_evidence(source)` index for this lookup.
Both remain repository ports; no store import leaks into engines or services.

## Acceptance criteria

- [ ] `source_context_enabled=false` preserves the pre-change recall block and all
      existing `info` keys for current fixtures; any new source-context counters are
      additive and report disabled/zero.
- [ ] A query that misses Artifact BM25 can find a recent Source and deliver its
      derived Artifact through the existing disclosure path.
- [ ] A cross-session Source is never rendered raw, including same-speaker and
      same-group fixtures; the negative tests assert the exact source text is absent.
- [ ] A same-session Source backing a secret/designated/shadow Artifact is not rendered
      raw by the Source fallback.
- [ ] Same-session recent Source text is rendered only as fallback and only within
      the remaining injection budget.
- [ ] Total memory block + source context is <= `budget_chars` (and estimated token
      output is reported).
- [ ] `chunk_turns` respects both turn and token limits, preserves all turns, and does
      not split a user/assistant reply pair.
- [ ] `IngestService` accumulates exact `usage_in`, `usage_cached`, `usage_out` from
      `ChatResponse` and preserves failed/retryable extraction semantics.
- [ ] `dream_token_budget` stops new extraction batches after the configured usage
      and writes usage/budget/stopped fields to the dream summary.
- [ ] Architecture tests still reject store imports from services/engines, aggregate
      `Store`/`DB` parameters and duplicate recall paths.
- [ ] Full test suite and package/architecture tests pass with the repository's
      Python environment.

## Tests to add or update

- `tests/test_source_context.py`: ranking, recency, same-session rendering, privacy
  negative cases, bounded output, factory/port fakes.
- `tests/test_recall_pipeline.py`: source-fallback integration through `build_block`
  and `RecallService.preview()`, disabled-mode compatibility, protected-source
  exclusion, and final-budget assertions.
- `tests/test_dream.py`: token-aware chunks, dream budget stop, usage summary.
- `tests/test_absorb.py` or `tests/test_failure_recovery.py`: extraction usage and
  retention on model failure.
- `tests/test_architecture_boundaries.py`: no new cross-layer imports; SourceStore
  and ArtifactStore are the only new read ports.
- `tests/test_public_interfaces.py`: new protocol method presence is typed and
  `WriteOutcome` usage fields default to zero.

## Implementation order

1. Add pure budget fields, Source disclosure decision and source ranking module with
   unit tests.
2. Add bounded SourceStore/ArtifactStore read methods and schema index.
3. Wire fallback through `recall/pipeline.py`; keep `RecallService` as the only entry.
4. Add extraction chunking, outcome usage and IngestService totals.
5. Add DreamCycle budget stop and BackgroundService usage callback.
6. Update schema/config/docs and run full acceptance.

## Risks and rollback

- Runtime cost: Source fallback adds one bounded SQL query and local BM25 only when
  Artifact recall is empty. Disable with `source_context_enabled=false`.
- Quality: Source ranking may surface older but related Artifacts; budget and
  disclosure still decide delivery.
- Extraction quality: smaller chunks can increase per-topic call count. The dream
  token budget caps total work; `extraction_chunk_tokens=0` can be treated as the
  legacy 120-turn behavior during rollback.
- No database rollback is required; the added index is inert and safe.

## Lead pre-review

- Ownership is explicit: one recall path, one extraction writer, no new service.
- Dependency direction is preserved: SQL stays in repositories, pure ranking/decisions
  live in `recall` and `core`, services receive protocols.
- Privacy is enforced before raw Source rendering; cross-session Source text is never
  used as output.
- Token budgets are bounded at both request injection and background extraction, with
  actual usage recorded rather than estimated only.
- The change is independently testable and has a disable switch for rollback.

## Chinese summary / 中文摘要

本议题同时解决两个已观察问题：

1. **抽取成本不可控**：Dream 抽取的单次对话输入没有 token 上限，整夜也没有
   总 token 停点，且台账没有记录模型 usage，账单无法归因。增加单批 token 上限、
   Dream 总预算、usage 累计与台账记录；到预算后停止提交新批次，但保留已提交
   结果并继续维护。
2. **Source 上下文不可用**：召回只读 Artifact，抽取延迟期间近期对话不可见，
   也缺少跨群聊的近期上下文。增加有界的 Source 近期窗口与本地排序，只作为
   Artifact 召回为空时的兜底；Source ID 可用于找到其派生 Artifact，最终仍然
   经过原有披露矩阵。

隐私边界：跨会话 Source 原文一律不注入。同一会话内才允许原文片段；跨群只允许
通过 Artifact 的披露等级形成连续性。隐私矩阵、RecallService 单一召回路径、
IngestService 单一抽取写入路径、store 不依赖上层等约束保持不变。

新增读取端口仅两个：`SourceStore.recent_sources()` 和
`ArtifactStore.by_source_ids()`。不新增服务、管理器、注册表、数据库表或写入路径。
