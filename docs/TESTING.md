# Testing Strategy

Tests are organized by the responsibility they protect, not by file size. The layer map lives in
`tests/layers.py`; the runner is `scripts/run_tests.py`.

## Layers

| Layer | What it protects | Typical tests |
|---|---|---|
| unit | Pure kernel, scoring, storage primitives, policy decisions | artifact, strength, store, gate, capacity |
| contract | Protocols, DTOs, OpenAPI and generated client shapes | public_interfaces, api_contract |
| integration | Several real components wired through a public use case | absorb, recall_pipeline, e2e_kernel |
| host | Real AstrBot lifecycle and plugin page bridge | webui_host |
| webui | Management service and journal behavior | webui, journal |
| smoke | Packaging, import and startup surfaces | smoke, package |
| benchmark | Retrieval quality, scale and ablations | benchmarks/*.py |

`all` runs every `tests/test_*.py` file.

## Commands

```bash
python3 scripts/run_tests.py --layer unit
python3 scripts/run_tests.py --layer contract
python3 scripts/run_tests.py --layer integration
python3 scripts/run_tests.py --layer host
python3 scripts/run_tests.py --layer all
```

The direct compatibility command remains:

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -q
```

## Rules for new tests

1. Use the production entry point when the behavior belongs to a use case.
2. Assert the final observable result, not only an intermediate candidate.
3. Add a negative test for every privacy boundary.
4. Add a recovery test for every write or model failure path.
5. Keep unit tests independent of SQLite files unless persistence is the subject.
6. Do not use the legacy `upsert` path to prepare a scenario that production writes through `commit`.
7. Prefer a small scenario matrix over duplicated copies of the same assertion.

## Coverage tracker

The table tracks covered regressions and known gaps. Rows marked as covered already have a regression test; the others should be added before or with the related fix.

| Gap | Target test |
|---|---|
| Same sentence from two users was deduplicated globally | covered by `tests/test_identity_isolation.py` |
| Similar impressions from two users cross-revised | covered by `tests/test_identity_isolation.py` |
| Shared impression was pinned and bypassed disclosure | covered by `tests/test_privacy_outputs.py` |
| Bad JSON was treated as an empty extraction | covered by `tests/test_failure_recovery.py` |
| Partial commit cleared the whole batch | covered by `tests/test_failure_recovery.py` |
| A batch above the topic limit loses unprocessed turns | covered by `tests/test_failure_recovery.py` |
| Legacy buffer dropped rows above 200 | covered by `tests/test_failure_recovery.py` |
| Corrupt pending JSON silently becomes an empty queue | covered by `tests/test_failure_recovery.py` |
| Pending save failure is silent | covered by `tests/test_failure_recovery.py` |
| Cached candidate was reinforced after budget trimming | covered by `tests/test_reinforcement.py` |
| Request failure recorded a hit | covered by `tests/test_webui_host.py` (host layer) |
| Designated output bypasses disclosure | covered by `tests/test_privacy_outputs.py` |
| Same memory counted twice inside cooldown | covered by `tests/test_reinforcement.py` |
| Source ids collided across sessions | covered by `tests/test_identity_isolation.py` |
| Revision lineage points to itself | lineage consistency |
| Cache removal succeeds after DB commit failure | cache/DB consistency |
| Similar scenes from different subjects merged together | covered by `tests/test_identity_isolation.py` |
| Relative date in query is not resolved | temporal scenario |
| Cancelled plan remains active | temporal scenario |
| Old database migration only checks a column | migration scenario |

## What tests cannot fully prove

- Real model extraction quality is probabilistic. Use schema tests, golden cases, sampling and staging probes.
- Persona emergence over months requires accelerated simulation and live trace review.
- Natural-language leakage cannot be proven by a single unit test. Combine boundary assertions, red-team prompts and
  final-output checks.
- Capacity and latency under real group traffic require staging load tests and production metrics.

## CI policy

CI runs the same file-level tests as the local compatibility command. Host-only tests may skip when the AstrBot
host is unavailable; that is not evidence that host behavior works. Record the host run separately in the PR.
