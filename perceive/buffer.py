"""Pending dialogue buffer with lightweight topic segmentation and TTL signals."""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict
from datetime import datetime

try:
    from ..app.contracts import DialogueTurn
except ImportError:
    from app.contracts import DialogueTurn

KEEP = 200
TOPIC_GAP_SECONDS = 5400
TOPIC_SIMILARITY = 0.12
TOPIC_TTL_SECONDS = 86400


def _parse_at(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value or ""))
    except (TypeError, ValueError):
        return None


def _bigrams(text: str) -> set[str]:
    clean = "".join(ch.lower() for ch in str(text or "") if ch.isalnum())
    return {clean[i:i + 2] for i in range(max(0, len(clean) - 1))}


def _dice(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return 2.0 * len(a & b) / (len(a) + len(b))


def _new_topic_id(turn: DialogueTurn) -> str:
    raw = f"{turn.session_id}|{turn.at}|{turn.text}"
    return "tp_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


class Buffer:
    def __init__(self, path: str = "") -> None:
        self.path = str(path or "")
        self.items: list[DialogueTurn] = []
        self.last_ts = 0.0
        self.load()

    def _last_for_session(self, session_id: str) -> DialogueTurn | None:
        for turn in reversed(self.items):
            if turn.session_id == session_id:
                return turn
        return None

    def add(self, umo: str, text: str, sender: str = "", source_id: str = "",
            at: str = "") -> DialogueTurn | None:
        text = str(text or "").strip()
        if not text:
            return None
        turn = DialogueTurn(str(umo or ""), str(sender or ""), "user", text,
                            str(at or ""), str(source_id or ""))
        previous = self._last_for_session(turn.session_id)
        turn = DialogueTurn(turn.session_id, turn.speaker_id, turn.role, turn.text,
                            turn.at, turn.source_id, self._topic_for(turn, previous))
        self.items.append(turn)
        self.items = self.items[-KEEP:]
        self.last_ts = time.time()
        self.save()
        return turn

    def _topic_for(self, turn: DialogueTurn, previous: DialogueTurn | None) -> str:
        if previous is None or not previous.topic_id:
            return _new_topic_id(turn)
        current_at, previous_at = _parse_at(turn.at), _parse_at(previous.at)
        if current_at is not None and previous_at is not None:
            if (current_at - previous_at).total_seconds() > TOPIC_GAP_SECONDS:
                return _new_topic_id(turn)
        if _dice(_bigrams(turn.text), _bigrams(previous.text)) < TOPIC_SIMILARITY:
            return _new_topic_id(turn)
        return previous.topic_id

    def topics(self) -> list[tuple[str, str, list[DialogueTurn]]]:
        groups: dict[tuple[str, str], list[DialogueTurn]] = {}
        for turn in self.items:
            groups.setdefault((turn.session_id, turn.topic_id), []).append(turn)
        return [(session, topic, rows) for (session, topic), rows in groups.items()]

    def idle_seconds(self) -> float:
        return max(0.0, time.time() - self.last_ts)

    def oldest_topic_age(self) -> float:
        stamps = [_parse_at(turn.at) for turn in self.items]
        valid = [stamp for stamp in stamps if stamp is not None]
        if not valid:
            return 0.0
        return max(0.0, (datetime.now() - min(valid)).total_seconds())

    def should_flush(self, idle_seconds: float, min_items: int) -> bool:
        if not self.items:
            return False
        return len(self.items) >= max(1, min_items) and self.idle_seconds() >= idle_seconds

    def take(self) -> list[DialogueTurn]:
        items = self.items
        self.items = []
        self.save()
        return items

    def take_topics(self, topic_ids: set[str]) -> list[DialogueTurn]:
        wanted = {str(x) for x in topic_ids}
        taken = [turn for turn in self.items if turn.topic_id in wanted]
        self.items = [turn for turn in self.items if turn.topic_id not in wanted]
        self.save()
        return taken

    def restore(self, rows: list[DialogueTurn]) -> None:
        if not rows:
            return
        existing = set(self.items)
        restored = [row for row in rows if row not in existing]
        self.items = (restored + self.items)[-KEEP:]
        self.save()

    def save(self) -> None:
        if not self.path:
            return
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump({"last": self.last_ts, "items": [asdict(t) for t in self.items]},
                          f, ensure_ascii=False)
        except Exception:
            pass

    def load(self) -> None:
        if not self.path:
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return
        if not isinstance(data, dict):
            return
        kept: list[DialogueTurn] = []
        for row in data.get("items") or []:
            turn = self._from_row(row)
            if turn is not None:
                kept.append(turn)
        self.items = kept[-KEEP:]
        try:
            self.last_ts = float(data.get("last") or 0.0)
        except (TypeError, ValueError):
            self.last_ts = 0.0

    @staticmethod
    def _from_row(row) -> DialogueTurn | None:
        if isinstance(row, dict):
            try:
                turn = DialogueTurn(str(row.get("session_id") or ""),
                                    str(row.get("speaker_id") or ""),
                                    str(row.get("role") or "user"),
                                    str(row.get("text") or ""),
                                    str(row.get("at") or ""),
                                    str(row.get("source_id") or ""),
                                    str(row.get("topic_id") or ""))
            except Exception:
                return None
        elif isinstance(row, (list, tuple)):
            if len(row) >= 5:
                turn = DialogueTurn(str(row[0]), str(row[1]), str(row[2]), str(row[3]),
                                    "", str(row[4]), "")
            elif len(row) == 4:
                turn = DialogueTurn(str(row[0]), str(row[1]), str(row[2]), str(row[3]))
            elif len(row) == 3:
                turn = DialogueTurn(str(row[0]), "", str(row[1]), str(row[2]))
            else:
                return None
        else:
            return None
        if not turn.text.strip():
            return None
        return turn if turn.topic_id else DialogueTurn(
            turn.session_id, turn.speaker_id, turn.role, turn.text,
            turn.at, turn.source_id, _new_topic_id(turn))
