# SeekMemory Invariants

These rules are normative. A change that violates one of them needs an explicit issue decision,
a migration plan and a contract or scenario test.

## 1. Identity

- `Source.id` identifies one immutable original message.
- A Source id must not collide across platform, session, role, speaker or event id.
- `said_by` means who produced the current Artifact content.
- `subject_id` means who the memory or impression is about.
- `origin_session` means where the evidence came from.
- The three fields are not interchangeable.
- Deduplication, impression revision and merge must be scoped by subject and privacy boundary.
  Two users saying the same sentence must not collapse into one memory.

## 2. Truth and versions

- Source is append-only. Capacity governance never deletes Source.
- Artifact is a derived interpretation.
- Production writes go through `artifacts.commit` with `expected_revision`.
- A committed Artifact is readable only after its version, evidence and ledger entry are written atomically.
- Cache is a derived view; a cache failure must not make the database look like a different truth.
- A batch operation must not report success when part of its input was not persisted.

## 3. Failure and recovery

- A model failure, invalid JSON, partial construction failure or commit failure must leave the input recoverable.
- Bad JSON and a legitimate empty array are different outcomes.
- A topic larger than the model window is split or retained; it is never silently marked complete.
- A corrupted pending file must not silently become an empty queue.
- A failed reply request must not reinforce artifacts that were never delivered.
- Every state-changing operation records a bounded error type or reason without logging message bodies.

## 4. Privacy and disclosure

- All outputs go through the same visibility and disclosure decision: dynamic recall, pinned persona/impression,
  designated delivery, shadow text and assembled prompt.
- `scope` decides whether an Artifact may be considered.
- `shareable` and disclosure decide how it may be expressed.
- `full` is the only level that may return raw content.
- Cross-session content must not return raw text merely because it is `shared`.
- Third-party identity and secret content must not be exposed because an impression was pinned.
- Logs and traces store ids, counts, enums and latency, not message bodies or model responses.

## 5. Reinforcement

- A memory is reinforced only when its Artifact id is present in the final assembled context.
- Candidates removed by deduplication, budget cuts, disclosure or failed requests are not reinforced.
- The final context contract must return the retained ids and drop reasons, not only a string.
- Repeated hits inside the cooldown window count once.
- A checkpoint failure leaves reinforcement retryable.

## 6. Time

- `created` is when the record was created.
- `event_at` is when the event happened.
- `updated` is when the Artifact revision was written.
- `last_used` is when recall last delivered it.
- `valid_from` and `valid_to` describe the validity period.
- `expires` is a lifecycle deadline.
- Relative time in the query must be resolved to a date range before retrieval.
- A cancelled plan or a changed fact must not keep competing with the current answer without a visible revision.

## 7. Data structure semantics

- `lineage.sources` is evidence. `lineage.derived_from` is abstraction lineage.
- A revision must not add its own id to `derived_from`.
- `state=forgotten` means not active for recall; it does not mean Source deletion.
- `shareable` is not a display label; it is part of the disclosure contract.
- `payload` is treated as immutable after commit. Mutating it in place bypasses cache and index consistency.
- Historical versions must preserve the disclosure-relevant header values.

## 8. Self-impression and persona (GitHub #15)

- A behavior is optional payload metadata, never a new Artifact family or SQL table.
- A behavior scene cites one immutable assistant Source and its actual user parent in the same session.
- Only distinct assistant evidence counts; duplicate artifacts, repeated extraction, recall hits and derived impressions do not add observations.
- At least three high-confidence (>= 0.9) observations form a self-impression.
- Self-impressions have `about=self`, `subject_id=bot:self`, `level=impression`, `scope=shared`, `said_by=inferred`.
- Shared self text is restricted to the six generic behavior templates. Private evidence stays in its protected original Sources.
- Persona comes only from those self-impressions, never from user traits, after the explicit seed bootstrap. Both promotion entry points obey this rule.
- A persona file bootstraps one initial `bot:self` persona revision with `origin=seed`, seed provenance, optional authored `corpus`, and no fabricated Source; it is not a second runtime profile.
- A bootstrap revision may store the authored corpus; later Dream revisions keep only `corpus_count`/`corpus_hash`, not the full corpus.
- Persona corpus is synthesis/reference data, not chat evidence and not recall-injected.
- After bootstrap, Dream may revise the same persona lineage automatically from active persona text plus bounded self-impressions/public memory summaries; every revision keeps evidence/audit and remains rollbackable.
- Later persona revisions do not duplicate full corpus; they keep only `corpus_count`/`corpus_hash` provenance.
- Persona synthesis is one bounded background call and never a recall read path.
- One active persona has a stable id; content/evidence changes add a revision, identical reruns do not. Consolidation is atomic.
- Unverified legacy persona cannot be injected; its original versions remain available for authenticated audit.
- Historical evidence comes from each version's own snapshot; current lineage cannot be substituted into history.
