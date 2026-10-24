# SeekMemory Architecture v4

## Core rule

Source is the only immutable truth. Artifact is a derived, versioned interpretation.

## Layers

```text
AstrBot events / cron / external input
        |
        v
main.py: composition and adapters only
        |
        v
app/: use cases, DTOs, ports
        |
        v
core/: Source, Artifact, Strength, versioning, disclosure
        ^
        |
store/ perceive/: SQLite, cache, LLM adapter
```

## Persistent model

- Source: source_id, turn_id, session_id, speaker_id, role, content hash, at, reply_to.
- Artifact: Header adds subject_id; payload follows family validators.
- artifact_versions: append-only full snapshots keyed by (entity, revision).
- state_events: lightweight cognitive deltas before a checkpoint.
- ledger: one event per committed Artifact revision.

## Write invariants

1. Source is idempotent and append-only.
2. Artifact commit uses expected_revision CAS.
3. One transaction writes blob, node head, version, evidence and ledger.
4. Cache is a derived view and updates only after commit.
5. LLM calls never run inside a DB transaction.

## Read and disclosure

Recall reads from in-memory indexes. Disclosure is one universal score:

exposure = context_affinity * subject_fit * scope_prior * topic_fit * (1 - sensitivity)

Levels: full >= 0.55, paraphrase >= 0.18, hint >= 0.03, otherwise silence.
Paraphrase uses a generic safe sentence, never raw content or extractor tags. Scope is a continuous prior, not a visibility gate. Cross-session text is only injected as a direct quote when context/subject affinity is high enough.

## I/O targets

- Recall: zero SQL reads after warmup; use cache indexes by family, level and subject.
- One user turn: append user and assistant Source rows; extraction commits a batch.
- Reinforcement: state_events in memory; checkpoint once per 30 minutes.
- SQLite is the first store; repository ports allow a later PostgreSQL adapter.

## Agent runtime boundary

AstrBot keeps generic chat history and tool-loop context. SeekMemory injects a protected system memory block through on_llm_request and captures assistant replies through on_llm_response. Extraction uses its own ChatModel port and does not reuse chat context.

## Retrieval extension

Retrieval follows the existing `app.ports.Retriever` protocol. `RetrievalCandidate` carries
activation and lexical signals. The default `GraphRetriever` remains seed/spread;
optional `HybridRetriever` preserves activation and adds normalized BM25 lexical evidence.

BM25 使用标准库字符 bigram 倒排索引，不调用模型或网络。正文/标签按 0.75/0.25 融合，
固定 `s/(s+8)` 归一化；仅以本次可见池计算 N、df 和平均长度。
插件入口持有长生命周期检索器，聊天与诊断共用；Cache.version 变化后重建派生索引。
`build_block(..., hybrid_retriever: Retriever | None = None)` 支持接口注入。
`bm25_enabled=true`，新配置 `bm25_weight=1.0`；select 函数默认权重 2.0 保留旧调用兼容。
BM25 本身无 SQL，现有 graph/source/history 路径仍可能查询 SQLite。
本次不包含本地向量实现，不新增 semantic 字段或依赖；后续边界记录在 ISSUE-0024。

All production writes now use `DB.commit()` with expected revision, version snapshots, evidence
links and ledger entries. `DB.upsert()` remains only as a legacy compatibility primitive.

## Topic, subject and time

Buffer entries are typed `DialogueTurn` objects. Topics split on a 90-minute gap or low
character-bigram similarity; `topic_ttl_seconds` forces aged topics to extraction.
The extractor returns `subject_kind`, `subject_id`, `event_at` and validity dates.
`TimeSpan.created` uses event time, not extraction time.

## Current implementation status (v0.4.0)

- Source is persisted for both user and assistant messages, including group sessions.
- Production writes use CAS DB.commit with versions, evidence and ledger.
- Topic-aware DialogueTurn buffer with 24h TTL extraction trigger.
- subject_kind/subject_id and event_at are part of extraction; Artifact created time is event time.
- Recall applies disclosure before assembly; cross-session text is never injected raw.
- Live validation: group sources and group Artifacts are being produced. A matching query selected
  two live Artifacts and applied paraphrase/silence disclosure.
- BM25 已接入，默认开启；实现及验收限制见 [ISSUE-0024](issues/ISSUE-0024.md)。
- Capacity governance is a pure `core/capacity.py` policy over Source, Pending,
  Artifact, Context and Trace metrics. Pending is rebuilt by joining
  `extraction_state` to immutable Source; it is not a second dialogue copy.
  The governor selects a state and bounded scheduler actions, while Source and
  Artifact history remain immutable/auditable.
- Under `backpressure` admission closes: new turns still persist their Source row
  but their extraction state is parked as `deferred`, and `release_deferred()`
  promotes them back once the governor returns to `normal`. Failed extractions
  back off and end in the terminal `dead` state instead of retrying forever.
- Extraction batches rotate one topic per session. The scheduler keeps its own
  bounded `webui/trace.py` ring for capacity samples, separate from the
  business Journal event log.
- Not implemented yet: local vector retrieval, general reflection signals and full RBAC.

## Robot self-impressions (GitHub #15)

User and assistant turns keep `turn_id` and `reply_to` in the pending projection.
An assistant reply inherits the actual parent topic; extraction can read an already
processed immutable parent as context without re-queuing it. Per-item evidence
is checked before deduplication. A behavior scene references exactly one real
user/reply pair, so one batch or several artifacts cannot inflate its frequency.

Weekly/dream maintenance aggregates self-impressions before decay and merge.
It requires at least three distinct assistant Sources with confidence >= 0.9,
then creates or revises a `bot:self` impression. User impressions remain independent.
The six v1 behaviors are responding to emotion, clarifying, admitting uncertainty,
offering choices, protecting privacy and correcting mistakes. Shared text comes
from fixed generic sentences, never extracted names, places or private facts.

Persona keeps one stable id and append-only revisions. Persona changes and any
duplicate-head retirement commit atomically. Old unverified persona text remains
in history but cannot enter chat context. No model/network call is added to chat
capture or recall; behavior fields use the existing background extraction call.
The admin timeline shows each revision's own lineage and protected dialogue evidence.

## Agent Runtime boundary

`app/runtime/` is host-agnostic and `AgentRuntime` is the single orchestration hub.
`SessionState` is mutable per-session runtime state, `RunDecision` is one attention/timing
decision, and `EpisodeRecord` is the append-only business audit row. `TimingPolicy` owns
pure time decisions, `Scheduler` owns due-session selection from persisted session state,
and `WakePolicy` owns inbound-event attention only. `RunRecorder`
is the single write-back service for assistant Source, pending buffer and runtime episode
records. AstrBot remains the transport/provider/platform host; `main.py` maps events into
`RuntimeInput` and must not move AstrBot types into the runtime package.

The gate is explicit. With `runtime_gate_enabled=false`, wait windows and deferred dispatch
are inactive; no runtime timer can cause a model call or message send. With the gate enabled,
deferred replies use the host provider directly; they do not run the full AstrBot tool loop.
Proactive generation remains a future feature.

## Runtime active path (v0.4.0)

The runtime has two production paths, and every retained runtime type must be reachable from one of them.

### Normal reply

```text
AstrBot message event
-> Buffer Source projection
-> AgentRuntime.observe()
-> optional event.should_call_llm() gate
-> MemoryContextPort
-> recall pipeline / disclosure
-> AstrBot model request
-> capture_reply()
-> RunRecorder.record_reply()
-> after_message_sent()
-> RunRecorder.record_delivery()
-> EpisodeRecord
```

### Deferred ambient reply

```text
runtime state with wait deadline
-> _runtime_scheduler_tick()
-> Scheduler + TimingPolicy
-> claim_dispatch()
-> provider.text_chat()
-> AstrBotActionPort.send()
-> RunRecorder.record_deferred_reply()
-> assistant Source + extraction buffer
-> EpisodeRecord
```

### Explicit boundaries

- Proactive generation is not implemented and has no scheduling path yet.
- `ToolPolicy.filter_tool_set()` filters `req.func_tool` before the model sees tools; the advisory
  `on_using_llm_tool` trace is not a veto.
- `RunRecorder` owns assistant Source, pending-buffer and episode write-back. Run id is the
  idempotency boundary so repeated callbacks cannot duplicate those writes.
- `RunTrace` is an admin observability stream, separate from the append-only runtime
  episode audit. It is not an Artifact or Source.
- `runtime_gate_enabled=false` keeps both wait and deferred dispatch inactive.

Cleanup rule: a runtime module or protocol without a production caller is either removed or
explicitly marked as a documented seam. Tests alone are not a reason to keep a production abstraction.

## Policy ownership

- `WakePolicy` owns inbound-event attention only; it does not duplicate timing decisions.
- `TimingPolicy` owns pure wait/retry deadline evaluation; inbound quiet/cooldown attention
  stays in `WakePolicy`.
- `Scheduler` owns querying persisted session state and reporting due runs. It does not send,
  generate, or mutate state.
- `ToolPolicy` owns both the enforced `req.func_tool` filter and the advisory tool-call trace.
  There is no second guard object for the same decision.
- `RunRecorder` owns completed-run write-back; `main.py` must not write assistant Source or
  episodes directly.
- `AgentRuntime` exposes only production transitions: observe, context build, wait clearing,
  dispatch claim, retry scheduling and delivery marking. Test-only mutation helpers are not
  part of the runtime API.
