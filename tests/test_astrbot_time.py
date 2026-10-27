"""AstrBot translates time to UTC+8 while leaving kernel contracts unchanged."""

from __future__ import annotations

import asyncio
import datetime
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adapters.astrbot_time import AstrBotBuffer, AstrBotRunRecorder, utc8_time  # noqa: E402
from app.runtime import AgentRuntime, InMemoryStateStore, RunContext, RuntimeInput  # noqa: E402
from core.source import Source  # noqa: E402
from store import open_store  # noqa: E402


class AstrBotTimeTest(unittest.TestCase):
    def test_offset_timestamps_become_utc8_in_the_existing_naive_shape(self) -> None:
        for raw in (
            "2026-10-27T16:00:00+00:00", "2026-10-27T12:00:00-04:00",
            "2026-10-28T00:00:00+08:00", "2026-10-28T00:00:00",
        ):
            self.assertEqual(utc8_time(raw), "2026-10-28T00:00:00")
        self.assertEqual(utc8_time("invalid"), "invalid")

    def test_user_normal_and_deferred_reply_share_utc8_at_write_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = open_store(str(Path(directory) / "memory.db"))
            try:
                episodes = []
                buffer = AstrBotBuffer(extraction=db.extraction)
                recorder = AstrBotRunRecorder(
                    sources=db.sources, buffer=buffer, checkpoint=None,
                    episodes=SimpleNamespace(record=episodes.append),
                )
                moment = datetime.datetime(
                    2026, 10, 27, 16, tzinfo=datetime.timezone.utc,
                ).timestamp()
                runtime = AgentRuntime(
                    InMemoryStateStore(), recorder=recorder, wait_seconds=5,
                    clock=lambda: moment + 10,
                )
                first = runtime.accept_user(
                    RuntimeInput("s1", "first", event_time=moment), now=moment,
                )
                runtime.record_reply(
                    run_id="normal", session_id="s1", text="normal reply",
                    speaker_id="bot", turn_id=first.turn_id, reply_to=first.source_id,
                    at="2026-10-27T16:00:01+00:00",
                )

                async def complete(*args):
                    return "deferred reply"

                async def send(*args):
                    return True

                runtime.model_gateway = SimpleNamespace(complete=complete)
                runtime.message_sender = SimpleNamespace(send=send)
                result = asyncio.run(runtime.dispatch_deferred(
                    RunContext("s1", "first", source_id=first.source_id), now=moment + 5,
                ))
                self.assertTrue(result.delivered)
                rows = db.extraction.pending_extractions()
                self.assertEqual([row["at"] for row in rows], [
                    "2026-10-28T00:00:00", "2026-10-28T00:00:01", "2026-10-28T00:00:10",
                ])
                self.assertEqual(episodes[-1].at, "2026-10-28T00:00:10")
                runtime.record_error(
                    run_id="error", session_id="s1", decision="reply", reason="error",
                )
                error_time = datetime.datetime.fromisoformat(episodes[-1].at)
                self.assertIsNone(error_time.tzinfo)
                buffer.reload()
                self.assertEqual([turn.at for turn in buffer.items], [row["at"] for row in rows])
            finally:
                db.close()

    def test_legacy_projection_converts_time_without_rewriting_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = open_store(str(Path(directory) / "memory.db"))
            try:
                old = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
                raw = old.isoformat(timespec="seconds")
                source = Source("u1", "t1", "s1", "u", "user", "same topic", raw)
                db.extraction.enqueue_extraction(source, "topic", raw)
                buffer = AstrBotBuffer(extraction=db.extraction)
                self.assertEqual(buffer.items[0].at, utc8_time(raw))
                self.assertAlmostEqual(buffer.last_ts, time.time() - 3600, delta=10)
                self.assertAlmostEqual(buffer.oldest_topic_age(), 3600, delta=10)
                self.assertEqual(db.sources.sources_by_ids(["u1"])["u1"].at, raw)
                buffer.add("s1", "same topic", "u", "u2", raw)
                self.assertEqual(buffer.items[0].topic_id, buffer.items[1].topic_id)
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
