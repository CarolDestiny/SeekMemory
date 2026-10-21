# Code Index

> Start here. Read this file, then docs/ARCHITECTURE.md, docs/CONTRACT.md and CONTRIBUTING.md.
> External contributors and agents must also read ../AGENTS.md.

## Current version

```text
v0.3.1
```

## Directory map

| Directory | Responsibility | Start here |
|---|---|---|
| core/ | Artifact and Source values, Strength, versioning, disclosure, retrieval values | core/README.md |
| app/ | Use-case DTOs, ports, flush policy, checkpoint orchestration | docs/ARCHITECTURE.md |
| store/ | SQLite repository, cache/read model, ledger | store/README.md |
| perceive/ | Extraction prompt, ChatModel adapter, topic buffer | perceive/README.md |
| recall/ | Candidate retrieval, scoring, disclosure-aware assembly | recall/README.md |
| maintain/ | Decay, merge, persona and reflection policies | maintain/README.md |
| tests/ | Unit, integration and kernel end-to-end tests | tests/test_kernel.py |
| docs/ | Architecture, contracts, issues, proposals | docs/BM25-PROPOSAL.md |
| main.py | AstrBot event mapping and composition only | main.py |

## Dependency direction

```text
main.py / AstrBot adapter
        |
        v
app/ use cases and ports
        |
        v
core/ Artifact kernel
        ^
        |
store/ perceive/ recall/ maintain/ adapters
```

Rules:

- core/ imports no storage, SDK, plugin or app code.
- app/ imports core/ only; external systems are behind ports.
- store/ is the only place that writes SQL.
- recall/ and maintain/ are migration zones; do not add new cross-layer dependencies.
- No module imports main.py.

## Write path

```text
AstrBot user message
  -> main.buffer_message
  -> Source(user) + DialogueTurn buffer with topic_id
  -> backlog / idle / nightly extraction
  -> ChatModel
  -> Artifact construction + validation
  -> DB.commit(expected_revision)
       -> blob
       -> node head
       -> artifact_versions
       -> artifact_evidence
       -> ledger
  -> cache.put

assistant reply
  -> main.capture_reply
  -> Source(assistant, reply_to=user source)
```

## Read path

```text
AstrBot on_llm_request
  -> recall.pipeline.build_block
  -> visible scope filter
  -> GraphRetriever (activation)
  -> select / evidence gate
  -> disclosure (full / paraphrase / hint / silence)
  -> assemble safe text
  -> system prompt
```

Recall does not write. Reinforcement is queued and flushed by app/checkpoint.py.

## Active design work

- BM25 hybrid retrieval: docs/BM25-PROPOSAL.md, ISSUE-0024.
- Future: reflection wiring, RBAC, capacity governance, persona source policy.

## Hard rules

1. Only core/artifact.py defines Artifact data structures.
2. Only store/db.py writes SQL.
3. All production writes use DB.commit with expected revision.
4. Source is immutable truth; Artifact is derived interpretation.
5. Cross-session content must pass disclosure before injection.
6. New P0/P1 work needs an issue and a PR record.
