# Public Interfaces

This page is for contributors who want to extend SeekMemory without reading the whole codebase. It describes the stable extension points, their contracts and the tests that protect them.

## Design rules

- Source is the only immutable truth.
- Artifact is a derived, versioned interpretation.
- Production writes go through ArtifactStore.commit with expected_revision.
- SQL lives only in store/db.py.
- Retrievers do not write.
- ChatModel is stateless. Context management belongs to the caller.

## Protocols in app/ports.py

### ChatModel

    async def complete(request: ChatRequest) -> ChatResponse

A provider adapter converts a provider-neutral request into one model call. It does not keep conversation state. ProviderChatModel is the built-in adapter.

### Retriever

    def retrieve(query: str, pool: list[Artifact]) -> list[RetrievalCandidate]

A retriever may score, rank or merge lexical and graph signals. It must only use the supplied visible pool. It must not write, call a model or query the database in a loop. GraphRetriever and HybridRetriever are built-in implementations.

### SourceStore

    def append_sources(sources: list[Source]) -> int

Append immutable Source rows. Repeating the same source id is idempotent.

### ArtifactStore

    def commit(art, *, expected_revision, op, reason="", source_ids=(), state_events=()) -> None
    def get(node_id: str) -> Artifact | None

commit writes the new head, append-only version, evidence, ledger and optional state events atomically. expected_revision is required. A stale writer must fail with VersionError. SQL must not be added outside store/db.py.

### StateStore

    def append_state_event(event: StateEvent) -> None
    def history(node_id: str) -> list[dict]

State events and history support reinforcement and audit. Production revisions should commit their state event together with the Artifact through ArtifactStore.commit.

### ExtractionStore

    def enqueue_extraction(source: Source, topic_id: str, created_at="", *, deferred=False) -> bool
    def put_extraction_state(state: ExtractionState) -> bool
    def pending_extractions(now="") -> list[dict]
    def queue_counts() -> dict[str, int]
    def release_deferred(limit=50) -> int
    def ready_extraction_ids(now="") -> set[str]
    def mark_extraction_succeeded(source_ids: list[str]) -> int
    def mark_extraction_failed(source_ids: list[str], error_type: str, *, max_attempts=5, now="") -> int

The pending queue is a projection. Source and extraction_state are inserted
atomically, content is read back from immutable Source, and completion never
deletes either row. Deferred rows wait for capacity headroom, and retries honor
`next_attempt_at` until they reach the terminal `dead` state.

## Shared DTOs in app/contracts.py

- DialogueTurn: one buffered turn; session_id, speaker_id, role and text are required.
- DialogueTurn also has trailing optional `turn_id=""`, `reply_to=None`; old positional calls remain valid.
- ChatRequest: provider-neutral request. max_tokens defaults to 800; temperature defaults to 0.0.
- ChatResponse: provider-neutral response with text required and usage fields optional.
- WriteOutcome: extraction result; distinguishes written, skipped, errors and model_failed.
- RecallRequest and RecallResult: boundary DTOs for callers that should not import the recall pipeline.
- RetrievalCandidate: Artifact plus activation and lexical scores. lexical is normalized to 0..1.

## Adding an interface or implementation

1. Open an issue for the interface change.
2. Add the protocol or DTO with a short docstring.
3. Add it to tests/test_public_interfaces.py.
4. Add one minimal built-in implementation.
5. Run the full test suite.

## Tests

    python3 -m unittest tests.test_public_interfaces -v
    python3 -m unittest discover -s tests -p 'test_*.py' -q

The contract tests check built-in implementations against runtime-checkable protocols and lock required DTO fields and defaults.

## Scope

This is the first contribution layer. It does not yet cover a plugin marketplace, third-party adapter certification or a public benchmark leaderboard.

## Two-sided evidence and self persona (GitHub #15)

`DB.sources_by_ids(ids) -> dict[str, Source]` bulk-reads immutable originals,
including session, speaker and reply links. Missing ids are omitted. Read errors
propagate so extraction can retain retryable input. It never updates queue state.

Extraction optionally returns `bot_behavior` (six values in `core/bot_behavior.py`),
`confidence` and `evidence_source_ids`. Behavior evidence must be exactly a valid
user/reply pair from the input. Its lineage and committed evidence use those same ids.
The four descriptive behavior fields remain optional and individually preserved.

Both `promote_candidates` and `distill_persona` keep their signatures but now use
only evidence-backed self-impressions. User traits are deliberately no longer
accepted as personality candidates. Three distinct observed replies at confidence
>= 0.9 bootstrap; age, recall hits and text repetition cannot replace evidence.

`persona.revisions[]` adds optional `derivedFrom` and `sourceIds` arrays. Each is
read from that revision's stored header, with empty arrays for missing historical
data. Status contains no original dialogue. The authenticated detail interface
supplies evidence on demand; the UI filters it to the selected historical version.

## Agent run trace (GitHub #11)

`RunTracer` in `app/runtime/tracing.py` depends only on a `TraceWriter.append(dict)` port.
`TraceStore` implements that port at the filesystem edge; all writes and reloads pass through
`clean_event`'s content-free whitelist. The trace is diagnostic metadata, not an Artifact write.

`GET manage/traces?state=all` requires the existing administrator session. It returns bounded
`runs`, `events`, `capacity`, `retention_days`, and `persistence_error`; see `openapi.yaml` for
strict field types and the four optional state filters. Unknown filters return 400. The API
remains available when the memory engine is unavailable. Run IDs are random, never session IDs.

`select(..., diagnostics=dict)` optionally fills gate counts and threshold without changing its
return value, ordering, exploration seed or privacy rules. A non-evaluated gate is distinct from
zero candidates passing an evaluated gate.

## Delivery and recovery (GitHub #61)

`build_block()` is read-only, including ordinary calls without `dry_run=True`.
Its info contains `designated_ids` and `designated_revisions` for designated bodies
actually retained by assembly. Historical impression notes use each revision's own
header and Source origins; snapshots without a reliable disclosure header are omitted.
`DB.history()` adds the stored `header` dictionary to each existing result row.

`RunRecorder.record_reply()` stages recall and designated IDs without reinforcing or
consuming memory. `record_delivery()` returns `bool`, confirms those effects after
successful transport delivery and raises on failed persistence. It also accepts explicit
`recall_ids`, `designated_ids` and `designated_revisions` for recovery. Completion is
memoized only after success; recent maps are bounded to 1024 entries by default, and
completed database episodes prevent replay after eviction or restart.

`EpisodeRecorder.record()` and built-in episode sinks return a success boolean.
`EpisodeRecorder.completed(run_id)` checks a durable delivered episode where supported;
`DB.runtime_episode_by_run_id(run_id)` returns that row or `None`.

`RunContext` adds trailing `speaker_id=""`; old positional fields retain their order.
`DB.latest_user_source()` includes the actual `speaker_id` from stored Source metadata.
`AgentRuntime.mark_delivered(..., read_through_seq=...)` acknowledges only that input
watermark, preserving later unread input and its waiting deadline.

`AgentRuntime(..., deferred_store=...)` accepts a `DeferredStore` port. Its temporary
`DeferredReply` stores the run ID, reply, parent Source, input watermark and delivery
effects separately from session state, traces and episodes. `DBDeferredStore` persists
this protected outbox through the DB facade. Sent rows are removed after successful
write-back. `recover_deliveries(now)` retries only local writes, even with the generation
gate disabled; it never invokes the model or sender. An interrupted or ambiguous send
retains an unresolved intent and is not automatically resent. Resolving that transport
uncertainty requires checking the platform; there is no transport receipt/query port yet.
