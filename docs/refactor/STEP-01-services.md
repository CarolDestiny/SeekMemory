# Step 1 - Services and Explicit Lifecycle

Status: merged in PR #67.

## Scope

- Rename `orchestration/` to `services/`.
- Use `*_service.py` file names for application services.
- Add `AccessService` and `BackgroundService`.
- Add frozen `ServiceCollection` as a typed data bundle.
- Move AstrBot runtime construction into idempotent `AstrBotPlugin.start()`.
- Make `Main` explicitly bind hooks and call `initialize()/terminate()`.
- Route hooks and WebUI through `plugin.services.*`.

## Dependency contract

```text
main.py
  -> adapters/
  -> services/
  -> app ports/runtime + domain engines
  -> repositories
```

- `ServiceCollection` has no registry, lookup, lifecycle or DI behavior.
- Hooks contain event mapping only.
- `main.py` contains composition and lifecycle only.
- Services are addressed by `*_service` attributes:
  `access_service`, `recall_service`, `ingest_service`, `capacity_service`,
  `maintenance_service`, `status_service`, `background_service`.
- `runtime` and `runtime_worker` remain runtime collaborators, not application
  service wrappers.

## ServiceCollection

```python
@dataclass(frozen=True)
class ServiceCollection:
    access_service: AccessService
    recall_service: RecallService
    ingest_service: IngestService
    capacity_service: CapacityService
    maintenance_service: MaintenanceService
    status_service: StatusService
    background_service: BackgroundService
    runtime: AgentRuntime
    runtime_worker: RuntimeWorker
```

## Acceptance evidence

- `main.py` explicitly lists all 9 AstrBot hooks; no `locals().update`.
- `Main.initialize()` starts the plugin and background jobs.
- `start_jobs` initializes services if the host fires the loaded hook first.
- `start -> stop -> start -> stop` is idempotent.
- DB initialization failure degrades safely.
- Hooks/WebUI/tests use `plugin.services.*`.
- Package allowlist contains `services/`.
- Local fake-host suite: 487 tests passed.
- Package + architecture tests: 23 passed.
- GitHub CI: test 3.10/3.11/3.12, frontend-contract, build all passed.
- Independent subagent review: APPROVE after lifecycle fixes.

## Next

- Step 2: `open_store()` repository bundle; remove public `DB` outside store.
- Step 3: explicit repository ports for maintain/recall/perceive.
- Step 4: consolidate duplicate write paths.
- Step 5: split `absorb`.
