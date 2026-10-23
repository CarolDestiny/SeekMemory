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
| Revision lineage pointed to itself | covered by `tests/test_lineage_consistency.py` |
| Cache removal succeeded after DB commit failure | covered by `tests/test_lineage_consistency.py` |
| Similar scenes from different subjects merged together | covered by `tests/test_identity_isolation.py` |
| Relative date in query was not resolved | covered by `tests/test_temporal.py` |
| Expired/future validity is ignored by recall | covered by `tests/test_temporal.py` |
| Old database migration only checked a column | covered by `tests/test_migration.py` |
| No continuous extraction-to-recall correction case | covered by `tests/test_continuity.py` |
| Explicit plan/fact replacement did not expire the old row | covered by `tests/test_continuity.py` |
| Batch merge left partial state after a member failure | covered by `tests/test_maintain.py` |
| Lifecycle expiry left partial forgotten state | covered by `tests/test_lifecycle.py` |
| Assistant replies were not captured as episodes | covered by `tests/test_webui_host.py` (host layer) |
| AgentRuntime policy was coupled to AstrBot | covered by `tests/test_agent_runtime.py` |
| Runtime social state was process-local only | covered by `tests/test_agent_runtime.py` |
| AstrBot event mapping was untested | covered by `tests/test_runtime_adapter.py` |
| Runtime actions, episodes and tool policy were untested | covered by `tests/test_runtime_actions.py` |
| Observe-only mode could accidentally change LLM gating | covered by `tests/test_webui_host.py` (host layer) |
| Runtime delivery was recorded before actual send | covered by `tests/test_webui_host.py` (host layer) |
| Runtime DB failures could break replies | covered by `tests/test_runtime_actions.py` |
| Runtime episode retention was unbounded | covered by `tests/test_runtime_actions.py` |
| User impressions were composed into persona | covered by `tests/test_self_impression.py` |
| Persona revision timeline was not exposed | covered by `tests/test_webui_host.py` (host layer) |
| Repeated bot behavior had no self-impression path | covered by `tests/test_self_impression.py` |
| Wait, quiet, proactive and per-session rate-limit scheduling were untested | covered by `tests/test_runtime_scheduler.py` |

## Staging and model probes

```bash
python3 scripts/snapshot_db.py --source /path/to/memory.db --destination /tmp/staging.db
python3 scripts/live_probe.py --db /path/to/memory.db --label live --json
python3 benchmarks/real_eval.py --cases benchmarks/data/extraction_smoke.jsonl --dry-run
```

`live_probe` is read-only and reports counts, extraction states, persona revision and ledger validity.
`real_eval` uses an OpenAI-compatible endpoint configured through `SEEKMEMORY_EVAL_BASE_URL`,
`SEEKMEMORY_EVAL_API_KEY` and `SEEKMEMORY_EVAL_MODEL`; it is a manual staging probe, not a CI replacement.

## What tests cannot fully prove

- Real model extraction quality is probabilistic. Use schema tests, golden cases, sampling and staging probes.
- Persona emergence over months requires accelerated simulation and live trace review.
- Natural-language leakage cannot be proven by a single unit test. Combine boundary assertions, red-team prompts and
  final-output checks.
- Capacity and latency under real group traffic require staging load tests and production metrics.

## CI policy

CI runs the same file-level tests as the local compatibility command. Host-only tests may skip when the AstrBot
host is unavailable; that is not evidence that host behavior works. Record the host run separately in the PR.
