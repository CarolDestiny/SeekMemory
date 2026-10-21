# ISSUE-0024 BM25 hybrid retrieval for Chinese memory recall

| item | value |
|---|---|
| id | ISSUE-0024 |
| level | P1 |
| status | open |
| date | 2026-10-21 |
| GitHub | [#4](https://github.com/NeverENG/SeekMemory/issues/4) |
| branch | feat/issue-0024-bm25 |
| proposal | docs/BM25-PROPOSAL.md |

## Problem

Current recall depends on character-bigram overlap, tags and graph activation. Queries that
paraphrase or reorder the original memory often return zero candidates.

RetrievalCandidate.lexical already exists, but no retriever fills it. This is the smallest
surface for adding BM25 without changing the cognitive model, evidence gate or disclosure rules.

## Scope

- Add a tokenizer boundary with a zero-dependency character-bigram default.
- Add an in-memory BM25 index with text and tag fields.
- Add HybridRetriever that merges graph activation and lexical scores.
- Add config keys bm25_enabled and bm25_weight.
- Keep BM25 off by default during shadow rollout.
- Calibrate evidence gate thresholds and lexical weight with benchmarks.
- Keep disclosure and cross-session privacy unchanged.

## Acceptance criteria

- [ ] BM25 index supports add/remove/search and normalized lexical scores.
- [ ] HybridRetriever returns one candidate per Artifact with activation and lexical.
- [ ] BM25 score contributes to evidence gate only through lexical evidence.
- [ ] Empty/punctuation-only queries produce zero lexical evidence.
- [ ] Recall remains correct when bm25_enabled is false.
- [ ] Unit tests cover tokenizer, index, hybrid merge and empty query.
- [ ] Ablation reports hit rate, noise, injected chars and latency on/off.
- [ ] Production default changes only after shadow and staging comparison.

## Implementation checklist

- [ ] recall/tokenizer.py
- [ ] recall/bm25.py
- [ ] Cache.version and index rebuild policy
- [ ] HybridRetriever
- [ ] recall/score.py configurable lexical weight
- [ ] config keys and docs
- [ ] tests/test_bm25.py
- [ ] benchmark before/after
