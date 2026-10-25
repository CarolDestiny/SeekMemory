# Final Consolidation Audit

Status: implementation complete, pending review/merge.

## Layer audit

    main.py
      -> adapters/astrbot_plugin.py, adapters/astrbot_hooks.py
      -> services/*_service.py
      -> app/runtime, app/ports, core/engines
      -> repositories
      -> store/

- main.py: 31 lines; explicit hook bindings and lifecycle only.
- AstrBotPlugin: the only production open_store() composition root.
- ServiceCollection: frozen typed data bundle; no registry, locator or DI.
- No DB symbol or store.db import outside store/.
- No aggregate Store import or db/store parameter in engine/service layers.
- perceive/absorb.py: pure conversion; no model call or writes.
- IngestService.extract: sole extraction writer.
- MaintenanceService: sole maintenance writer.
- RecallService.preview: sole WebUI recall path.
- RunRecorder: sole completed-run conversation writer.

## Trace dependency cleanup

- Moved pure trace projection from app/runtime/trace_data.py to core/trace.py.
- store/run_trace.py now imports core.trace, removing the store -> app inversion.
- app/runtime/tracing.py imports core.trace.
- Architecture tests now reject store imports of app/, adapters/ or astrbot.

## Verification

- Local fake-host suite: 495 tests passed (all except environment-bound
  test_api_contract.py and test_webui_host.py).
- Package + architecture tests: 31 passed.
- compileall and git diff --check clean.
- Full five-step acceptance records live under docs/refactor/.

## Residual notes

- RunTracer still stores per-event trace state through the host event's
  get_extra/set_extra interface. It has no AstrBot import and is guarded by the
  runtime boundary test, but it remains the narrow host-facing part of run
  tracing.
- Database schema and transaction semantics were not changed during Steps 1-5.
