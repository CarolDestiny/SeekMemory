"""Temporal validity and relative date windows for recall."""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from typing import Iterable

try:
    from ..core.artifact import Artifact
except ImportError:
    from core.artifact import Artifact


def as_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def valid_at(art: Artifact, today: date | None = None) -> bool:
    """Return whether an Artifact may be used on the given day."""
    moment = today or date.today()
    span = art.header.time
    lower = as_date(span.valid_from)
    upper = as_date(span.valid_to)
    expiry = as_date(span.expires)
    if lower is not None and moment < lower:
        return False
    if upper is not None and moment > upper:
        return False
    if expiry is not None and moment > expiry:
        return False
    return True


def filter_valid(arts: Iterable[Artifact], today: date | None = None) -> list[Artifact]:
    return [art for art in arts if valid_at(art, today)]


def _next_month(day: date) -> date:
    return date(day.year + (1 if day.month == 12 else 0),
                1 if day.month == 12 else day.month + 1, 1)


def query_window(text: str, today: date | None = None) -> tuple[date, date] | None:
    """Resolve common Chinese relative expressions into an inclusive date range."""
    raw = str(text or "")
    moment = today or date.today()
    if "\u4eca\u5929" in raw:
        return moment, moment
    if "\u660e\u5929" in raw:
        one = moment + timedelta(days=1)
        return one, one
    if "\u6628\u5929" in raw:
        one = moment - timedelta(days=1)
        return one, one
    if "\u4e0b\u5468" in raw:
        start = moment - timedelta(days=moment.weekday()) + timedelta(days=7)
        return start, start + timedelta(days=6)
    if "\u8fd9\u5468" in raw or "\u672c\u5468" in raw:
        start = moment - timedelta(days=moment.weekday())
        return start, start + timedelta(days=6)
    if "\u4e0b\u4e2a\u6708" in raw:
        start = _next_month(moment)
        end = date(start.year, start.month,
                   calendar.monthrange(start.year, start.month)[1])
        return start, end
    if "\u8fd9\u4e2a\u6708" in raw or "\u672c\u6708" in raw:
        start = date(moment.year, moment.month, 1)
        end = date(moment.year, moment.month,
                   calendar.monthrange(moment.year, moment.month)[1])
        return start, end
    if "\u660e\u5e74" in raw:
        start = date(moment.year + 1, 1, 1)
        return start, date(moment.year + 1, 12, 31)
    if "\u4eca\u5e74" in raw:
        return date(moment.year, 1, 1), date(moment.year, 12, 31)
    return None


def event_date(art: Artifact) -> date | None:
    span = art.header.time
    return as_date(span.created) or as_date(span.valid_from)


def in_window(art: Artifact, window: tuple[date, date] | None) -> bool:
    if window is None:
        return True
    day = event_date(art)
    if day is None:
        return False
    return window[0] <= day <= window[1]
