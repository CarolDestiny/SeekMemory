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

exposure = audience_overlap * subject_fit * topic_fit * (1 - sensitivity)

Levels: full >= 0.50, paraphrase >= 0.18, hint >= 0.03, otherwise silence.
Paraphrase uses tags, never raw content. Cross-session text is never injected as a direct quote.

## I/O targets

- Recall: zero SQL reads after warmup; use cache indexes by family, level and subject.
- One user turn: append user and assistant Source rows; extraction commits a batch.
- Reinforcement: state_events in memory; checkpoint once per 30 minutes.
- SQLite is the first store; repository ports allow a later PostgreSQL adapter.

## Agent runtime boundary

AstrBot keeps generic chat history and tool-loop context. SeekMemory injects a protected system memory block through on_llm_request and captures assistant replies through on_llm_response. Extraction uses its own ChatModel port and does not reuse chat context.
