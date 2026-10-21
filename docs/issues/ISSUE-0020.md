# ISSUE-0020 Artifact kernel and version chain foundation

| item | value |
|---|---|
| id | ISSUE-0020 |
| level | P1 |
| status | closed |
| date | 2026-10-21 |
| branch | refactor/issue-0020-artifact-kernel |

## Problem

Source and Artifact semantics were not explicit. Source was never persisted in production, versions could be overwritten, and writes were split across independent side effects.

## Decision

- Source is the only immutable truth source.
- Artifact is a derived, versioned interpretation.
- Artifact adds subject_id only; privacy context is derived at runtime.
- Every committed state change gets a new revision and CAS.
- Cognitive changes use lightweight StateEvent rows plus 30-minute checkpoints.
- Disclosure uses one exposure score and four levels: full / paraphrase / hint / silence.

## First slice

- core/source.py
- core/versioning.py
- core/disclosure.py
- app/contracts.py and app/ports.py
- SQLite CAS commit, append-only artifact_versions, state_events
- subject_id migration
- perceive/model.py ChatModel adapter
- architecture and kernel tests
