## Summary

## Related issue

Closes #

## Changes

-

## What was intentionally not changed

## Verification

- [ ] syntax check
- [ ] unit tests
- [ ] benchmark / ablation
- [ ] real AstrBot staging probe
- [ ] live probe (Lead-approved only)

Commands and results:

## Data and privacy impact

- Source evidence:
- Artifact field/version changes:
- DB migration:
- Cross-session disclosure:
- Logging impact:

## Risk and rollback

## Agent checklist

- [ ] I read AGENTS.md and docs/ARCHITECTURE.md.
- [ ] Production writes use DB.commit().
- [ ] No SQL outside store/db.py.
- [ ] No secrets or message bodies in logs.
- [ ] New behavior has a regression test.
- [ ] The Lead has reviewed deployment steps.
