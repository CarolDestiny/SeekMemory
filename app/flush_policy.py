from __future__ import annotations

from dataclasses import dataclass

BACKLOG_QUIET_SECONDS = 30.0


@dataclass(frozen=True)
class FlushDecision:
    should: bool
    reason: str


def decide_flush(*, pending: int, idle_seconds: float, worth_now: bool,
                 flushes_today: int, idle_flush_seconds: float,
                 min_pending: int, max_flushes_per_day: int,
                 backlog_flush_at: int,
                 topic_age_seconds: float = 0.0,
                 topic_ttl_seconds: float = 86400.0) -> FlushDecision:
    if topic_ttl_seconds > 0 and topic_age_seconds >= topic_ttl_seconds:
        return FlushDecision(True, "topic_expired")
    if flushes_today >= max(1, int(max_flushes_per_day)):
        return FlushDecision(False, "daily_cap")
    if backlog_flush_at > 0 and pending >= int(backlog_flush_at):
        quiet_need = BACKLOG_QUIET_SECONDS
        if idle_seconds >= quiet_need:
            return FlushDecision(True, "backlog")
        return FlushDecision(False, "backlog_wait")
    if idle_flush_seconds <= 0:
        return FlushDecision(False, "idle_disabled")
    if pending < max(1, int(min_pending)):
        return FlushDecision(False, "below_min")
    if idle_seconds < idle_flush_seconds:
        return FlushDecision(False, "not_idle")
    if not worth_now:
        return FlushDecision(False, "not_worth")
    return FlushDecision(True, "worth_now")
