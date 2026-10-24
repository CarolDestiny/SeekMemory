# store/ - persistence

SQLite, the in-memory cache, the artifact ledger and bounded run traces live here.
**Only this package writes SQL.**

## One database, several repositories

`store/db.py` is a thin composition root. It owns one `SqliteDatabase` connection and
exposes domain repositories; it contains no SQL.

| file | responsibility |
|---|---|
| `sqlite.py` | connection, PRAGMA, schema, migrations, shared serialization helpers |
| `db.py` | composition only: `db.artifacts`, `db.sources`, `db.extraction`, `db.runtime_state`, `db.runtime_episodes`, `db.dreams`, `db.ledger`, `db.metrics` |
| `artifacts.py` | nodes, blobs, versions, artifact_versions, edges, evidence, state_events, commit/read/history |
| `sources.py` | immutable Source append/read and Source-only projections |
| `extraction.py` | extraction queue admission, retry/dead state, counts |
| `runtime_state.py` | mutable per-session scheduler/runtime state |
| `runtime_episodes.py` | append-only runtime audit episodes |
| `dreams.py` | daily dream-run ledger |
| `metrics.py` | cross-domain read-only capacity counters |
| `ledger.py` | hash-chain append/read/verify |
| `cache.py` | active Artifact read model |
| `run_trace.py` | bounded JSONL run traces |
| `schema.sql` | schema definition |

## Transaction boundaries

- Artifact commit: `blobs + nodes + versions + artifact_versions + evidence + state_events + ledger` in one transaction.
- Source admission: `blobs + sources + extraction_state` in one transaction.
- Runtime state and runtime episodes are separate from Source/Artifact memory.
- Repositories share one connection; they never open their own database file.

## Boundaries

- `store/` does not import AstrBot or adapters.
- No SQL outside `store/`.
- `core/` never imports `store/`.
- Read rows fail open: malformed legacy rows are skipped or returned as empty values.
