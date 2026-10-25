# Step 5 - Conversion and Write Split

Status: implementation complete, pending review/merge.

## Scope

- perceive/absorb.py is now pure conversion and validation.
- The public absorb() coroutine was removed.
- recover_parents() is read-only Source recovery.
- build_plan() parses model output, validates evidence, deduplicates and
  constructs validated Artifacts. It does not commit, cache, link, supersede or
  revise impressions.
- IngestService.extract() owns the model call and every write side effect:
  Artifact commit, cache update, link creation, supersede and impression revision.
- IngestService.flush() delegates each chunk to extract().
- Tests use tests/absorb_support.py, which exercises the production
  IngestService.extract() path rather than a second test-only write path.

## Dependency contract

    IngestService.extract()
      -> recover_parents()            read-only Source lookup
      -> model call
      -> build_plan()                 pure parse/validate/construct
      -> ArtifactStore.commit()
      -> Cache / Graph / supersede / impression revision

perceive/absorb.py has no repository writes and no model call.

## Acceptance

- perceive.absorb has no absorb attribute.
- Only IngestService imports perceive.absorb in production code.
- build_plan has no commit/cache/graph/revise_impression calls.
- IngestService.extract preserves WriteOutcome behavior:
  parent/model/parse/evidence failures, construct skips, commit skips,
  supersede/impression best-effort errors, and retryable flags.
- Journal stages still report provider.call, response.parse,
  memory.deduplicate, artifact.validate and artifact.persist.
- Tests cover the same production path through IngestService.

## Verification

- Local fake-host suite: 495 tests passed (all except environment-bound test_api_contract.py and test_webui_host.py).
- Package + architecture tests: 31 passed.
- compileall clean.
- Fake AstrBot lifecycle verifies no public absorb() coroutine and the
  service-level extract() entrypoint exists.

## Next

- Final consolidation review and documentation cleanup.
