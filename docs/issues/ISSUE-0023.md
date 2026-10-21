# ISSUE-0023 Topic buffer, subject attribution and event time

| item | value |
|---|---|
| id | ISSUE-0023 |
| level | P1 |
| status | open |
| date | 2026-10-21 |
| branch | feat/issue-0023-topic-subject-time |

## Problem

Dialogue buffering was a flat list, extraction attributed every item to the current speaker,
and Artifact created time was extraction time rather than event time.

## Decision

- Buffer stores DialogueTurn objects with source_id, at and topic_id.
- Topic assignment uses session, a 90-minute gap and character-bigram similarity.
- Oldest topic age can force extraction through topic_ttl_seconds.
- Extraction prompt requires subject_kind, subject_id, subject_name, event_at and validity dates.
- Artifact TimeSpan.created comes from event_at with Source timestamp fallback.
- Owner attribution resolves through an explicit owner_id passed from the plugin boundary.
