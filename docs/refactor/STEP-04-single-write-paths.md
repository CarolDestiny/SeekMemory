# Step 4 - Single Write Paths

Status: implementation complete, pending review/merge.

## Scope

- CapacityService no longer imports maintain modules or writes merge/forget state itself.
- MaintenanceService owns capacity-triggered compact and forget operations.
- CapacityService still owns capacity policy, deferred release, trace trim and alerts.
- RecallService gains dry_run support and preview().
- ManagementService preview delegates to RecallService.preview().
- WebUI no longer imports or calls recall.pipeline.build_block directly.
- IngestService remains the only production caller of perceive.absorb.

## Dependency rules

    BackgroundService -> CapacityService -> MaintenanceService
    WebUI -> ManagementService -> RecallService.preview()
    BackgroundService -> IngestService -> absorb

MaintenanceService is the single owner of maintenance writes.
RecallService is the single owner of the recall read path.
IngestService is the single owner of extraction orchestration.

## Acceptance

- capacity_service.py contains no maintain imports.
- capacity_service.py calls maintenance.compact_artifacts() and
  maintenance.forget_expired().
- webui/service.py contains no build_block or recall.pipeline imports.
- diagnose() returns RecallService.preview() unchanged shape.
- IngestService is the only production module importing absorb.
- Architecture guards cover all three invariants.

## Verification

- Local fake-host suite: 493 tests passed (all except environment-bound test_api_contract.py and test_webui_host.py).
- Package + architecture tests: 29 passed.
- compileall clean.
- Focused WebUI and recall pipeline tests pass.

## Next

- Step 5: split absorb into pure conversion plus IngestService orchestration.
