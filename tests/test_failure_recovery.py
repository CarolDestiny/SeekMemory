"""Failure recovery regressions: malformed output, partial commit and legacy buffer."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.contracts import DialogueTurn  # noqa: E402
from core.graph import Graph  # noqa: E402
from perceive.absorb import absorb  # noqa: E402
from perceive.buffer import Buffer  # noqa: E402
from perceive.extract import ExtractionParseError, parse_response, parse_response_checked  # noqa: E402
from store.cache import Cache  # noqa: E402
from store.db import DB  # noqa: E402


class FakeProvider:
    def __init__(self, text: str) -> None:
        self.text = text

    async def text_chat(self, system_prompt: str = "", prompt: str = ""):
        class Resp:
            completion_text = self.text

        return Resp()


def _db():
    path = os.path.join(tempfile.mkdtemp(prefix="seekmem_recovery_"), "t.db")
    db = DB(path)
    return db, Cache(db), Graph(db, Cache(db))


def _turn(text: str = "hello") -> DialogueTurn:
    return DialogueTurn("umo:a", "10001", "user", text, "2026-10-22T12:00:00", "s1")


class ParseRecoveryTest(unittest.TestCase):
    def test_bad_json_is_not_a_valid_empty_result(self) -> None:
        with self.assertRaises(ExtractionParseError):
            parse_response_checked("not json at all")
        self.assertEqual(parse_response("not json at all"), [])

    def test_empty_array_is_a_valid_empty_result(self) -> None:
        self.assertEqual(parse_response_checked("[]"), [])


class AbsorbRecoveryTest(unittest.TestCase):
    def test_bad_json_is_retryable(self) -> None:
        db, cache, graph = _db()
        outcome = asyncio.run(absorb(
            [_turn()], db, cache, graph, FakeProvider("not json at all"),
        ))
        self.assertTrue(outcome.model_failed)
        self.assertTrue(outcome.retryable)
        self.assertEqual(outcome.written, 0)

    def test_valid_empty_array_is_a_completed_empty_batch(self) -> None:
        db, cache, graph = _db()
        outcome = asyncio.run(absorb(
            [_turn()], db, cache, graph, FakeProvider("[]"),
        ))
        self.assertFalse(outcome.model_failed)
        self.assertFalse(outcome.retryable)
        self.assertEqual(outcome.written, 0)
        self.assertEqual(outcome.skipped, 1)

    def test_partial_commit_is_retryable(self) -> None:
        db, cache, graph = _db()
        original = db.commit
        calls = {"count": 0}

        def flaky_commit(*args, **kwargs):
            calls["count"] += 1
            if calls["count"] == 2:
                raise RuntimeError("second commit failed")
            return original(*args, **kwargs)

        db.commit = flaky_commit
        raw = json.dumps([
            {"level": "fact", "text": "first fact"},
            {"level": "fact", "text": "second fact"},
        ])
        outcome = asyncio.run(absorb(
            [_turn()], db, cache, graph, FakeProvider(raw),
        ))
        self.assertEqual(outcome.written, 1)
        self.assertTrue(outcome.retryable)
        self.assertTrue(outcome.errors)


class BufferRecoveryTest(unittest.TestCase):
    def test_legacy_buffer_keeps_more_than_200_rows(self) -> None:
        path = os.path.join(tempfile.mkdtemp(prefix="seekmem_legacy_"), "pending.json")
        buf = Buffer(path)
        for index in range(250):
            buf.add("umo:a", f"message {index}")
        self.assertEqual(len(buf.items), 250)
        self.assertEqual(len(Buffer(path).items), 250)


if __name__ == "__main__":
    unittest.main()
