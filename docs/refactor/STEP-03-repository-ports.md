# Step 3 - Explicit Repository Ports

Status: implementation complete, pending review/merge.

## Scope

- Add narrow repository protocols in app/ports.py:
  ArtifactStore, SourceStore, ExtractionStore, MetricsStore, LedgerStore.
- Make Tree and Graph depend on an artifact repository instead of an aggregate Store.
- Convert maintain functions to accept artifacts and sources directly.
- Convert recall pipeline and designated delivery to accept artifacts and sources.
- Convert absorb to accept artifacts and sources directly.
- Convert RecallService, IngestService, CapacityService, MaintenanceService and
  StatusService constructors to receive repositories.
- Convert ManagementService to receive artifacts, sources and ledger.
- Keep AstrBotPlugin as the only composition root that opens Store.

## Dependency contract

    adapters/astrbot_plugin.py
      -> open_store()
      -> service constructors receive repository ports
      -> engines receive only the repositories they use
      -> store repositories implement the protocols

No engine or service imports Store, DB, SQLite or store.db.
No engine or service function takes a db argument.

## Single owner direction

- IngestService: extraction write orchestration.
- MaintenanceService: maintenance write orchestration.
- RecallService: recall orchestration; delivery state is written through ArtifactStore.
- CapacityService: policy and capacity-triggered actions only.
- AstrBotPlugin: composition and lifecycle only.

## Acceptance

- Tree(artifacts, cache) and Graph(artifacts) only.
- maintain/decay, merge, persona, self-impression and link accept explicit repos.
- recall/pipeline.build_block(cache, graph, artifacts, sources, ...).
- perceive/absorb(items, artifacts, sources, cache, graph, model, ...).
- Service constructors receive repo fields, not Store.
- webui ManagementService receives artifacts, sources, ledger.
- Public protocol tests cover ArtifactStore, SourceStore, ExtractionStore,
  MetricsStore and LedgerStore.
- Architecture guard rejects Store imports and db parameters in engines/services.

## Verification

- Local fake-host suite: 490 tests passed (all except environment-bound test_api_contract.py and test_webui_host.py).
- Package + architecture tests: 26 passed.
- compileall clean.
- Fake AstrBot lifecycle verifies service repositories are the Store repositories.

## Next

- Step 4: consolidate duplicate write paths and route WebUI preview through RecallService.
- Step 5: split absorb into pure conversion plus IngestService orchestration.
