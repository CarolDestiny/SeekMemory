# ISSUE-0035: Measure the Dream triage tradeoff

Status: verified (measurement complete; triage algorithm intentionally unchanged).

## Problem

PR #79 reduced Dream calls and tokens by adding deterministic importance triage,
same-session batching, real call/token budgets and content-free usage accounting.
The optimization deliberately trades extraction/self-impression coverage for cost,
but the tradeoff was only covered by synthetic unit/integration tests. There was no
fixed measurement of pre/post calls, tokens, missed important facts, false memory,
duplicates, bot-behavior/self-impression coverage or pending backlog.

## Proposal delivered

- Frozen 40-topic synthetic corpus in `benchmarks/data/dream_tradeoff_corpus.jsonl`
  (SHA-256 `173daf5403bc28d47daff59fcd9dbd864d4225180cf22f78a49974a361cad3e0`):
  24 user-fact topics, 8 bot-behavior episodes, 5 low-value chatter topics and 3
  backlog topics across 3 sessions.
- `benchmarks/dream_eval.py` runs the production
  `DreamCycle -> IngestService.flush` path against an isolated in-memory SQLite
  store with a deterministic recorded provider. No network, no real chat content,
  no second Artifact write path.
- `benchmarks/dream_tradeoff.py` runs each checkout in its own process and renders
  the `cc814ce` / `d9fc248` comparison, pending-growth simulation and explicit
  thresholds in `benchmarks/results/dream_tradeoff.md`.
- `tests/test_dream_eval.py` guards determinism, content-free reports and the
  single Artifact write path.

## Recorded results

| metric | cc814ce | d9fc248 |
|---|---:|---:|
| Extraction calls | 40 | 8 |
| `usage_in` | 62,585 | 15,230 |
| `usage_cached` | 0 | 0 |
| `usage_out` | 5,614 | 3,293 |
| Total tokens | 68,199 | 18,523 |
| Calls with >1 topic | 0 | 5 |
| Important-fact recall | 23/23 (100.0%) | 15/23 (65.2%) |
| Bot-behavior coverage | 8/8 (100.0%) | 7/8 (87.5%) |
| Self-impression coverage | 1/1 (100.0%) | 0/1 (0.0%) |
| False-memory rate (modeled) | 20.5% | 0.0% |
| Duplicate rate | 0.0% | 0.0% |
| Pending topics | 0 | 17 (9 important, 8 low-value) |
| Oldest pending age | 0.000 d | 0.778 d |

Pending growth simulation: 8 low-value topics per night produce 8 → 16 → 24 pending
topics over three nights, with the oldest age rising 0.744 → 1.744 → 2.744 days.
The queue is unbounded under Dream-only triage.

## Thresholds and verdict

Pre-registered thresholds: important-fact recall >= 85%, bot-behavior coverage >= 85%,
self-impression coverage >= 85%, false-memory rate <= 10%, duplicate rate <= 2%,
pending ratio <= 50%, call reduction >= 50% and token reduction >= 50%.

Result: `NOT_ACCEPTED`. Efficiency passes (calls -80.0%, tokens -72.8%), but
important-fact recall (65.2%) and self-impression coverage (0/1) fail, and pending
growth is unbounded. The measurement does not change the triage algorithm.

## Missed important facts

`peanut_allergy`, `moved_beijing`, `birthday`, `grandma_health`, `quit_smoking`,
`work_city`, `best_friend`, `stress` (one topic each). The behavior episode
`C11_behavior_comfort_missed` is also below the threshold; it is the third
`respond_emotion` episode, so its loss collapses the only expected self-impression
from 1/1 to 0/1.

## Follow-up recommendations

1. Extend first-person/possessive triage coverage for the eight missed fact classes.
2. Decouple behavior-episode admission from user-memory triage, or add a
   behavior-first lane, so one missed episode does not erase an impression.
3. Add a bounded pending policy (age-based escalation/re-triage or explicit discard).
4. Keep same-session batching; it produced the measured savings with no duplicate
   regression in this corpus.
5. Add a holdout corpus before tuning on these numbers.

## Limitations

Synthetic hand-authored corpus; deterministic recorded provider; character-based
token estimate with no cache simulation; no live AstrBot host; one run per target.
`d9fc248` and the current tree share the same production extraction code, so their
identical metrics validate the harness. `cc814ce` predates the triage/budget
parameters; the harness filters unsupported kwargs and runs the same production
flush path without triage.

## Acceptance checklist

- [x] At least 30 frozen labeled topics covering user facts, bot behavior,
      low-value chatter and backlog.
- [x] One command produces calls, tokens, extraction yield and quality metrics
      deterministically.
- [x] Before/after comparison recorded for `cc814ce` and `d9fc248` with the same
      input and fake/recorded outputs.
- [x] Report states whether the tradeoff is acceptable under explicit thresholds.
- [x] Pending count/age reported; unbounded growth risk called out.
- [x] Regression test verifies the harness uses `IngestService` and cannot become a
      second production write path.
- [x] Existing test suite and architecture guards remain green (the only local
      exception is the pre-existing sandbox-only `test_package` subprocess case,
      which fails identically on the unmodified baseline).
- [x] No raw conversation content committed.

## Related

- PR #79: token control, Source evidence recall and Dream triage
- `docs/issues/ISSUE-0033-token-source-context.md`
- ISSUE-0031: request-side context budget
- ISSUE-0024: BM25 retrieval boundary
- Report: `benchmarks/results/dream_tradeoff.md`
