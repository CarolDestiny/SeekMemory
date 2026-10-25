# ISSUE-0033: Token control, Source-evidence recall and Dream triage

- Status: verified (pending merge)
- Priority: P1
- Owner: application services, with pure policy helpers
- Related: ISSUE-0024 (BM25), ISSUE-0028 (capacity/Source projection), ISSUE-0031 (request context budget)
- Supersedes: none

## Background / Why this issue exists

SeekMemory has two related gaps:

1. Background extraction has no real model-call ceiling. `dream_max_batches`
   bounds topic batches, not actual extraction calls, and the dream ledger does
   not record model usage.
2. Recall only ranks active Artifacts. During the extraction delay, recent
   dialogue remains available only as immutable Source evidence, so recall can
   miss an existing derived Artifact that a Source query would discover.

The solution must keep Source internal as evidence. Source raw text must never be
rendered into the prompt. Source ids may discover Artifacts, but only the existing
Artifact visibility/disclosure path decides what reaches the model.

## Goals / Scope

- Add memory-first Source evidence discovery: one bounded recent-Source query and
  one batch `by_source_ids` lookup only when Artifact selection is weak.
- Keep Source text out of blocks, info, logs and assembly.
- Add an actual-call Dream budget (`dream_max_calls`, default 12).
- Keep exact extraction usage accounting.
- Keep one recall owner (`RecallService`) and one extraction writer (`IngestService`).
- No new service, manager, registry, DI container or database table.

## Non-goals

- No raw Source injection, HINT rendering or Source privacy matrix.
- No vector database, embedding service, network call or chat-path model call.
- No token-based extraction chunking; keep original `MAX_TOPIC_TURNS` behavior.
- No favorability, proactive speech, ImportService, persona UI or additional Dream quality ranking beyond deterministic importance triage.
- No change to Artifact fields, CAS/version/evidence/ledger semantics or Source truth.
- No automatic schema migration beyond additive read indexes.

## Ownership decision

| Semantics | Owner |
|---|---|
| SQL for recent Sources and Artifact-by-Source lookup | `SourceStore` / `ArtifactStore` repository ports |
| Source candidate ranking, ids/hits only | new pure module `recall/source_query.py` |
| Single recall composition and delivery marking | `RecallService` / `recall/pipeline.py` |
| Extraction call budget and usage accumulation | `IngestService` |
| Dream stop condition and summary merge | `DreamCycle` called by `BackgroundService` |
| Budget parsing and token estimation | `app/budget.py` |
| Privacy | existing Artifact visibility and disclosure only |

AccessService remains the recall permission gate. Source candidates may cross
sessions; there is no second hard Source-origin privacy gate.

## Design

### 1. Memory-first Source evidence discovery

The normal Artifact retrieval/selection runs first. Let `recall_k` be the configured
Artifact recall capacity. Only when both conditions hold may Source evidence be queried:

- `len(picked) < min(2, recall_k)`
- `intent_of(text) != "none"`

Then issue exactly one `SourceStore.recent_sources(since, limit)` query and one
`ArtifactStore.by_source_ids(source_ids)` batch. Source candidates may come from any
session. Filter discovered Artifacts through existing `visible`, `deliverable`,
`filter_valid` and query-window rules, deduplicate against `picked`, and append only up
to the remaining `recall_k` capacity. Run the single existing Artifact disclosure and
assembly pass afterward. Pinned persona/impression never gates Source evidence lookup.

Source ids are internal evidence only. Source text is never in the block, info, logs or
assembly. The query result is content-free counters such as enabled, candidates,
artifacts, picked and matched. `source_recall_enabled=false` preserves the legacy
empty-recall info shape. The fallback never writes Source, delivery state or
reinforcement; only assembled Artifact ids can be marked delivered as before.

### 2. Source query

`recall/source_query.py` is pure. It ranks recent immutable Sources with local
character-bigram BM25 plus recency/session/speaker scores and returns `SourceHit`
values containing only source id, score, lexical score and same-session flag. It makes
no model call and returns no Source text. Clock, greeting and empty queries do not
enter the query. A Source whose normalized text equals the current query is excluded.

### 3. Extraction call budget and usage

`chunk_turns` keeps the original turn-only `MAX_TOPIC_TURNS` behavior. There is no
`extraction_chunk_tokens` and no `ExtractionBudget`.

`IngestService.flush(..., max_calls=..., max_tokens=...)` checks the remaining call
allowance and the actual input+output token delta before starting each real extraction
call. Unstarted pending rows remain recoverable. `DreamCycle` uses `dream_max_calls`
(default 12) as the primary budget, passes both remaining budgets to the flush callback,
and records budget/usage/stopped in the dream summary. `dream_token_budget` is an
optional secondary guard with at most one-call slack. Maintenance semantics are
unchanged.

`IngestService` records exact `usage_in`, `usage_cached`, and `usage_out` from each
`ChatResponse` on `WriteOutcome` and exposes a content-free cumulative
`usage_snapshot()`, including parse/evidence/partial-commit outcomes reached after a
successful model call.

### 4. Dream importance triage

Before any Dream provider resolution or model call, `IngestService.split_topics(...,
triage=True)` uses pure `perceive/importance.py` to score pending topics from user
turns only. Categories are distinct and reason labels are content-free: explicit
remember/reminder 4, identity/profile 3, preference/boundary 3, relationship/family 3,
plan/commitment 3, privacy/boundary 4, significant event 2, strong emotion 1, and
self-recall question 2. The default threshold is 2.0. Ties order by latest timestamp
then topic id. Assistant-only topics, greetings, acks and generic commands score low.

Identity, preference and relationship signals require first-person/possessive forms or
direct personal context. Plan signals require first-person commitment or a personal
date+action phrase; bare date words do not score. Self-recall questions are not
extraction evidence. Pure assistance commands score zero unless they also contain a
strong personal-memory signal (explicit remember, privacy, or first-person identity/
preference/relationship/plan). Bare single-character family/pet terms do not score.

Selected high-value topics proceed through the existing extraction path and budgets.
Dream-only same-session batching packs already-chunked topic units into one call within
the `dream_batch_tokens` budget (default 6000) plus a reserved prompt estimate. One batch
is one real extraction call; a single topic chunk is never split further. Cross-session
batching is out of scope because extraction/evidence validation assumes one session.
Multi-topic batches add topic labels and require every extracted item to cite non-empty
evidence IDs from one topic; missing, invalid or cross-topic evidence is retryable and
lineage is never widened to all batch sources. Single-topic batches retain default
rendering and legacy fallback.
Low-value topics remain pending unchanged; there is no skipped state and no Source
deletion. Only `DreamCycle` passes `triage=True`; nightly/idle extraction keeps FIFO
selection. Journal metadata is category/count only (`candidates`, `eligible`,
`selected`, `skipped_low_value`, `batches`, `calls`), never topic text. The pipeline
ranks pending topics once per flush and derives selection/counters from that same ranked
list.

Known tradeoff: selecting by user-memory value can narrow self-impression coverage
because assistant-only or otherwise low-value interaction topics may not be selected.

### 5. Repository ports

```python
class SourceStore(Protocol):
    def recent_sources(self, *, since: str, limit: int) -> list[Source]: ...

class ArtifactStore(Protocol):
    def by_source_ids(self, source_ids: list[str]) -> list[Artifact]: ...
```

`SourceRepository.recent_sources` uses indexed `sources.at` ordering.
`ArtifactRepository.by_source_ids` joins `artifact_evidence` with
`ae.revision = n.revision` and active nodes only. Add indexes on `sources(at)` and
`artifact_evidence(source)`. No store import leaks into engines or services.

## Acceptance criteria

- [x] Memory sufficient -> no Source query.
- [x] Weak memory -> at most one Source query and one `by_source_ids` batch.
- [x] Source-derived Artifacts fill only remaining recall capacity and pass existing
      visibility/disclosure.
- [x] Source text never appears in block, info, logs or assembly.
- [x] Cross-session Source query can discover an existing Artifact.
- [x] Pinned persona/impression does not gate Source evidence lookup.
- [x] `source_recall_enabled=false` preserves legacy empty-recall info shape.
- [x] `by_source_ids` remains revision-scoped.
- [x] `chunk_turns` original turn-only behavior remains.
- [x] Exact usage accounting survives parse failure/partial success.
- [x] `dream_max_calls` stops before exceeding the limit and leaves pending rows.
- [x] Dream summary records budget/usage/stopped; maintenance unchanged.
- [x] Architecture guards reject store imports in engines/services, duplicate recall
      paths and extraction writers.
- [x] Focused, full, architecture/package and `scripts/run_tests.py --layer all`
      compatible tests pass.
- [x] Dream triage is local/deterministic and runs before provider resolution.
- [x] Low-value topics remain pending and unmarked.
- [x] Non-Dream FIFO selection is unchanged.
- [x] Triage journal metadata is category/count only.

## Tests

- `tests/test_source_query.py`: ranking, cross-session hits, revision-scoped lookup.
- `tests/test_recall_pipeline.py`: memory-first threshold, one query/one batch,
  remaining-capacity fill, pinned bypass, no Source text, disabled shape.
- `tests/test_absorb.py`: exact usage and IngestService call-budget pending retention.
- `tests/test_dream.py`: call-budget stop, token secondary guard, summary metadata.
- `tests/test_architecture_boundaries.py`, `tests/test_public_interfaces.py`.
- `tests/test_importance.py`: scoring categories, category dedupe, recency/cap ordering.
- Dream triage: high-value selected, low-value pending without model calls, non-Dream
  FIFO preserved, budgets still enforced.

## Risks and rollback

- Source evidence query adds one bounded Source SQL read plus one Artifact batch only
  when Artifact selection is weak; disable with `source_recall_enabled=false`.
- No new database table or Artifact field; added indexes are inert.
- `dream_max_calls` bounds actual extraction calls; pending rows remain recoverable.
- Token budget is secondary and may allow one-call slack; actual-call budget is primary.
