# Persona File and Bootstrap

## Purpose

A persona file is authored configuration that initializes the one active persona
chain. It is not a Source, not chat evidence, and not a second runtime profile.

The seed-content owner authors files. `ManagementService.bootstrap_persona()` is
the admin write path. After bootstrap, Dream owns further persona revisions.

## File format

A persona file is a UTF-8 JSON object.

```json
{
  "id": "big_fish",
  "version": "1.0.0",
  "name": "大肥鱼",
  "persona": "你是大肥鱼，说话温柔但有点嘴硬。",
  "style": {
    "tone": "温柔嘴硬",
    "sentence_length": "short"
  },
  "boundaries": [
    "不伪造用户经历",
    "不透露私人 Source 原文"
  ],
  "corpus": [
    {"user": "今天好累。", "assistant": "先歇一下嘛，我陪你。"},
    {"user": "你会不会走？", "assistant": "才不走呢，别乱想。"}
  ],
  "license": "CC0-1.0",
  "source": "original",
  "content_rating": "general",
  "locale": "zh-CN"
}
```

### Required fields

| Field | Rule |
|---|---|
| `id` | Lowercase letters, digits, `.`, `_`, `-`; 2–64 chars |
| `version` | Non-empty string, max 32 chars |
| `name` | Non-empty display name, max 80 chars |
| `persona` | Non-empty persona text, max 20,000 chars |
| `corpus` | Non-empty authored dialogue corpus, max 64 entries |

`persona_text` is accepted as a compatibility alias for `persona` in the early
draft, but new files should use `persona`.

### Optional fields

- `style`: bounded JSON object; used by future composition, not evidence.
- `boundaries`: bounded string array.
- `corpus`: authored style dialogues. This is required because a persona prompt
  alone cannot reproduce a distinctive voice. Corpus is stored with the persona
  provenance but is **not** chat evidence and is **not** injected into recall.
  It is the reference material for persona synthesis (see below).
- `license`, `source`, `content_rating`, `locale`.

Unknown fields are rejected so the file format cannot silently absorb unsafe
metadata.

## Bootstrap contract

`bootstrap_persona(persona_file)`:

1. validates the file;
2. finds the current active persona;
3. creates or revises the same persona Artifact id;
4. writes payload provenance (`origin=seed`, `seed_id`, `seed_version`,
   `seed_license`, `seed_source`, style, boundaries, corpus, corpus_count,
   corpus_hash);
5. sets the persona header to `bot:self`, `shared`, `public`, `said_by=seed`;
6. commits atomically and updates cache;
7. retires duplicate active persona rows if legacy data contains them;
8. returns id, revision and seed provenance.

It must not:

- create a Source;
- call extraction or Dream;
- write a second PersonaProfile table;
- let the WebUI write storage directly.

## After bootstrap

The initial seed persona is trusted for recall. Dream may later revise the same
persona Artifact lineage from memory/impressions:

```text
seed persona + corpus
  + Dream memory/impressions
  = new persona Artifact revision on the same id
```

The current bootstrap foundation preserves `corpus`, `corpus_count` and
`corpus_hash` across revisions. It does not inject the corpus into every recall
prompt and does not pretend the deterministic behavior composer is a full style
synthesis. A follow-up persona-synthesis step should consume the corpus plus
approved impressions and produce a reviewed/rollbackable persona revision.

The previous revision remains in history. Rollback and manual edits must use the
same persona Artifact lineage. A future implementation may add a one-click
rollback operation, but it must not create a parallel persona store.

## Trust rules

- Seed-origin persona: trusted only with explicit seed provenance and an active
  `bot:self` shared/public header.
- Dream-origin persona: must retain evidence lineage and the existing
  confidence/derived-from checks.
- Legacy behavior-derived persona: preserve the existing fixed-text rules.
- Arbitrary unverified persona text: never injected.

## Storage

- Authored files: `persona_seeds/` (read-only runtime data, packaged by the
  seed/store owner).
- Installed state: persona Artifact rows plus payload provenance.
- No separate active persona profile table is needed for this bootstrap.
- Chat imports remain Source/Dream writes; they are not persona files.
