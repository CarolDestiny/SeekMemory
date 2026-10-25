from __future__ import annotations

from dataclasses import dataclass

from .budget import estimate_messages
from .contracts import DialogueTurn

BACKLOG_QUIET_SECONDS = 30.0
MAX_TOPIC_TURNS = 120


@dataclass(frozen=True)
class FlushDecision:
    should: bool
    reason: str


def _is_pair(parent: DialogueTurn, reply: DialogueTurn) -> bool:
    """True when ``reply`` is the assistant answer to ``parent``."""
    if reply.role != "assistant" or parent.role != "user":
        return False
    if reply.session_id != parent.session_id:
        return False
    if reply.reply_to and reply.source_id:
        return str(reply.reply_to) == str(parent.source_id)
    return bool(reply.turn_id) and str(reply.turn_id) == str(parent.turn_id)


def chunk_turns(
    items: list[DialogueTurn],
    limit: int = MAX_TOPIC_TURNS,
    max_tokens: int = 0,
) -> list[list[DialogueTurn]]:
    """Split one topic by turn and estimated-token limits.

    Adjacent user/assistant reply pairs are treated as indivisible units. A unit
    that alone exceeds a limit is retained as one oversized chunk rather than
    being split or dropped. ``max_tokens=0`` keeps the legacy turn-only behavior.
    """
    size = max(1, int(limit))
    token_cap = max(0, int(max_tokens))
    units: list[list[DialogueTurn]] = []
    index = 0
    while index < len(items):
        if index + 1 < len(items) and _is_pair(items[index], items[index + 1]):
            units.append(items[index:index + 2])
            index += 2
        else:
            units.append([items[index]])
            index += 1

    chunks: list[list[DialogueTurn]] = []
    current: list[DialogueTurn] = []
    current_tokens = 0
    for unit in units:
        unit_tokens = estimate_messages([turn.text for turn in unit])
        exceeds_turns = bool(current) and len(current) + len(unit) > size
        exceeds_tokens = (
            token_cap > 0 and bool(current) and current_tokens + unit_tokens > token_cap
        )
        if current and (exceeds_turns or exceeds_tokens):
            chunks.append(current)
            current = []
            current_tokens = 0
        current.extend(unit)
        current_tokens += unit_tokens
        if len(current) >= size or (token_cap > 0 and current_tokens >= token_cap):
            chunks.append(current)
            current = []
            current_tokens = 0
    if current:
        chunks.append(current)
    return chunks


def select_topic_batches(
    items: list[DialogueTurn], cap: int
) -> list[tuple[str, str, list[DialogueTurn]]]:
    """Pick one topic per session in turn until ``cap`` batches are chosen.

    Round-robin over sessions keeps a single long conversation from occupying
    every slot; sessions with more queued topics contribute again on later passes.

    Args:
        items: queued dialogue turns.
        cap: maximum number of topic batches to return.

    Returns:
        ``(session, topic_id, rows)`` batches in selection order.
    """
    buckets: dict[str, dict[str, list[DialogueTurn]]] = {}
    order: list[str] = []
    for turn in items:
        session = str(turn.session_id or "")
        if session not in buckets:
            buckets[session] = {}
            order.append(session)
        buckets[session].setdefault(str(turn.topic_id or ""), []).append(turn)
    limit = max(1, int(cap))
    queues = {session: list(buckets[session].items()) for session in order}
    cursors = {session: 0 for session in order}
    selected: list[tuple[str, str, list[DialogueTurn]]] = []
    while len(selected) < limit:
        advanced = False
        for session in order:
            queue = queues[session]
            cursor = cursors[session]
            if cursor >= len(queue):
                continue
            topic_id, rows = queue[cursor]
            cursors[session] = cursor + 1
            selected.append((session, topic_id, rows))
            advanced = True
            if len(selected) >= limit:
                break
        if not advanced:
            break
    return selected


def decide_flush(*, pending: int, idle_seconds: float, worth_now: bool,
                 flushes_today: int, idle_flush_seconds: float,
                 min_pending: int, max_flushes_per_day: int,
                 backlog_flush_at: int,
                 topic_age_seconds: float = 0.0,
                 topic_ttl_seconds: float = 86400.0,
                 dream_only: bool = False) -> FlushDecision:
    # 梦境模式下白天一律不抽：进化只发生在 dream 周期里。
    # 放在最前面，连 topic 过期也不越过它，否则白天又会被触发。
    if dream_only:
        return FlushDecision(False, "dream_only")
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
