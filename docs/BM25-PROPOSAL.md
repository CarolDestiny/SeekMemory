# BM25 Retrieval Proposal

Status: proposal only, no implementation in this document.

Goal: add a cheap lexical retriever that improves Chinese recall without introducing an embedding
service, while keeping the existing cognitive score, evidence gate and privacy rules intact.

## 1. Current state

- `recall/seed.py` finds seeds from character bigrams and tags.
- `recall/spread.py` adds graph activation.
- `recall/retriever.py` returns RetrievalCandidate(artifact, activation, lexical=0).
- `recall/score.py` already accepts a normalized lexical signal, but no retriever fills it.
- The evidence gate counts lexical evidence, so BM25 can integrate without changing the read model.

Primary gap: a query must share literal bigrams or tags with a memory. Synonyms and reordered
Chinese phrases still fail (ISSUE-0001).

## 2. Proposed components

### 2.1 Tokenizer boundary

Add `recall/tokenizer.py` with a small protocol:

    tokenize(text: str) -> list[str]

Default implementation: Unicode character bigrams after lowercasing and stripping punctuation.
This keeps the current zero-dependency behavior. A later Jieba or external tokenizer can implement
the same protocol without changing the index or scoring code.

### 2.2 BM25 index

Add `recall/bm25.py`:

- Document fields: `content_for(artifact)` and `tags`.
- Inverted index: token -> postings of (doc_id, term_frequency).
- Track document length and average length.
- Support `add`, `remove`, `search`.
- Default parameters: k1=1.2, b=0.75.
- Score text field and tag field separately:

    lexical = 0.75 * normalize(bm25_text) + 0.25 * normalize(bm25_tags)

Normalization is per query: divide by the maximum raw score so lexical is in [0, 1].

### 2.3 Hybrid retriever

Extend `recall/retriever.py` with a HybridRetriever:

1. GraphRetriever produces activation scores.
2. BM25 search produces lexical scores.
3. Union candidates by artifact id.
4. Return RetrievalCandidate(artifact, activation, lexical).

No retrieval logic moves into main.py.

## 3. Scoring and evidence gate

`recall/score.py` already adds `2.0 * lexical` to both score and evidence. Make this configurable:

    select(..., lexical_weight=2.0)

Recommended initial weight: 1.5 to 2.0. It must be calibrated against the existing evidence gate;
BM25 must not become a new prior that lets unrelated high-frequency documents pass.

Rules:

- lexical evidence counts only when the query has at least one non-stopword token;
- empty or punctuation-only queries produce zero lexical evidence;
- BM25 is a ranking and evidence source, never a privacy decision;
- disclosure still runs after selection.

## 4. Index lifecycle and I/O

- Build from the active cache at startup; no SQL read during recall.
- Add a monotonically increasing `Cache.version`, bumped on put/remove/load.
- `HybridRetriever` rebuilds the index when the cache version changes.
- Rebuild cost is O(active nodes  average tokens). At the current scale this is negligible; measure
  at 5k and 20k nodes before considering a persistent index.
- No network calls. No DB transaction is held during retrieval.
- Future upgrades: SQLite FTS5 shadow table, Tantivy, or an embedding retriever behind the same
  Retriever protocol.

## 5. Config

Add only two config keys:

- `bm25_enabled` (bool, default false during shadow rollout)
- `bm25_weight` (float, default 2.0)

The tokenizer, k1 and b remain code constants until benchmark data justifies exposing them.

## 6. Change footprint estimate

New files:

- `recall/tokenizer.py`: about 50-80 lines
- `recall/bm25.py`: about 140-200 lines
- `tests/test_bm25.py`: about 150-220 lines

Modified files:

- `recall/retriever.py`: about 50-90 lines
- `recall/pipeline.py`: 10-20 lines
- `recall/score.py`: 10-20 lines
- `store/cache.py`: 5-10 lines for version tracking
- `app/flush_policy.py` or config schema: only if extraction gating changes (not required)
- `docs/ARCHITECTURE.md`, `docs/index`, `CHANGELOG.md`, `metadata.yaml`: release changes

Total estimate: 350-600 lines including tests and docs, excluding benchmark tuning.

## 7. Test plan

Unit tests:

- tokenizer normalization and empty input;
- BM25 idf and score monotonicity;
- field weighting text vs tags;
- add/remove/reindex behavior;
- hybrid union and duplicate elimination;
- normalized lexical range [0, 1];
- empty query returns zero lexical evidence.

Integration tests:

- a memory that current bigram seeds miss but BM25 finds through token overlap;
- disclosure still downgrades cross-session matches;
- evidence gate rejects unrelated high-frequency text.

Benchmarks:

- `benchmarks/run.py`, `benchmarks/scale.py`, `benchmarks/ablation.py`;
- compare hit rate, noise ratio, injected chars and latency with bm25 on/off;
- attach numbers to the PR before changing defaults.

## 8. Rollout

1. Land tokenizer + BM25 index + tests only.
2. Run HybridRetriever in shadow mode: log lexical scores but do not change selection.
3. Enable bm25 in staging and compare benchmark deltas.
4. Enable in production only if noise does not regress and hit rate improves.
5. Keep bm25_enabled as a rollback switch.

## 9. Risks and decisions

- Chinese bigrams can over-match common character pairs; IDF and length normalization mitigate this.
- BM25 and the existing literal feature can double-count evidence; tune weights against the gate.
- Rebuilding on every cache mutation can be expensive at large scale; measure before adding a persistent index.
- A future embedding retriever must implement the same Retriever protocol and produce a calibrated
  lexical-equivalent signal, not bypass disclosure or the evidence gate.

## 10. Out of scope

- Vector embeddings, rerankers and external search services.
- Changing persona or impression extraction.
- Changing privacy/disclosure levels.
- Replacing the current cognitive scoring model in one step.
