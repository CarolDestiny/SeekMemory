# ISSUE-0021 Pending backlog can starve extraction and flush can drop sessions

| item | value |
|---|---|
| id | ISSUE-0021 |
| level | P1 |
| status | open |
| date | 2026-10-21 |
| branch | feat/issue-0021-backlog-flush |

## Problem

`_should_flush()` only flushes when `worth_now()` matches. A busy but casual day can accumulate
a large pending buffer until the nightly run. In addition, `_flush()` took the entire buffer
and then processed only `max_sessions_per_flush` sessions, dropping all other sessions.

## Decision

- Add `backlog_flush_at` (default 30).
- A backlog flush requires only a 30-second quiet window and ignores `worth_now`.
- Respect the existing daily flush cap.
- Take only selected sessions from the buffer.
- Keep unselected sessions in `pending.json`.
- Add pure `app/flush_policy.py` with unit tests.
