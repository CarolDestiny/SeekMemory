# Step 2 - Repository Store Boundary

Status: implementation complete, pending review/merge.

## Scope

- Replace the public `DB` class with `store.open_store(path) -> Store`.
- `Store` is the only SQLite composition container.
- `Store` exposes repositories and `close()` only; it has no domain methods.
- Delete `store/db.py`.
- Rename plugin state from `self.db` to `self.store`.
- Rename repo-backed runtime adapters:
  - `DBStateStore` -> `RepoStateStore`
  - `DBEpisodeStore` -> `RepoEpisodeStore`
- Update callers, tests, scripts and benchmarks to `open_store`.
- Add architecture guard: no `store.db` or public `DB` imports outside `store/`.

## Dependency contract

```text
composition root -> open_store(path) -> Store
Store -> repository implementations
repositories -> SqliteDatabase -> SQLite
```

Application code receives repositories; it must not import `DB` or open SQLite.

## Acceptance

- `store/db.py` does not exist.
- `store/__init__.py` owns `Store` and `open_store`.
- `AstrBotPlugin` stores `self.store`, never `self.db`.
- Runtime adapters are repository-backed and contain no `DB` naming.
- Tests/benchmarks/scripts use `open_store`.
- Architecture test rejects `store.db` and `DB` imports outside store.
- Artifact/Source transaction semantics remain unchanged.

## Verification

- Local fake-host suite: 488 tests passed.
- Package + architecture tests: 24 passed.
- `compileall` clean.
- On-demand fake AstrBot lifecycle: start/stop/restart passes.

## Next

- Step 3: pass explicit repository interfaces into maintain/recall/perceive.
- Remove remaining aggregate `Store` usage from services.
- Consolidate duplicate write paths and split `absorb`.
