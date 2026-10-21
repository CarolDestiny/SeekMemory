# ISSUE-0022 Consolidate writes, disclosure and retrieval boundary

| item | value |
|---|---|
| id | ISSUE-0022 |
| level | P1 |
| status | open |
| date | 2026-10-21 |
| branch | feat/issue-0021-backlog-flush |

## Problem

After the Artifact kernel landed, several production write paths still used legacy
`DB.upsert()`, recall did not yet apply subject-aware disclosure, and retrieval had no
stable candidate boundary for a future BM25 implementation.

## Decision

- Move decay, merge, persona, tree and designated writes to CAS `DB.commit()`.
- Reuse the same persona id across revisions instead of creating a new id per update.
- Apply disclosure before assembly and pass only safe text overrides to the renderer.
- Add `core.retrieval.RetrievalCandidate` and `recall.retriever.GraphRetriever`.
- Reserve `lexical` for a future BM25 retriever.
- Mark source-less legacy extractions with lower confidence instead of inventing evidence.
