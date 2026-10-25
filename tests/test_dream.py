"""梦境周期与上下文预算的回归测试。"""

from __future__ import annotations

import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.budget import (  # noqa: E402
    ContextBudget,
    ExtractionBudget,
    budget_from_config,
    clamp_chars,
    estimate_tokens,
    extraction_budget_from_config,
)
from app.contracts import DialogueTurn  # noqa: E402
from app.dream import DreamCycle  # noqa: E402
from app.flush_policy import chunk_turns, decide_flush  # noqa: E402


class FakeStore:
    """最小台账桩：只实现 dream 相关读写。"""

    def __init__(self) -> None:
        self.runs: dict[str, dict] = {}

    def get(self, date):
        return self.runs.get(date)

    def begin(self, date, now=""):
        run = self.runs.get(date)
        if run and run.get("status") == "done":
            return False
        self.runs[date] = {"date": date, "status": "running", "started_at": now}
        return True

    def finish(self, date, *, status="done", batches=0, written=0,
                     errors=None, summary=None, now=""):
        self.runs[date] = {"date": date, "status": status, "batches": batches,
                           "written": written, "errors": errors or [],
                           "summary": summary or {}, "finished_at": now}

    def recent(self, limit=7):
        return list(self.runs.values())[:limit]


def conf(**kw):
    """配置桩：给定键优先，其余回默认。"""
    def _c(key, default):
        return kw.get(key, default)
    return _c


AT = datetime.datetime(2026, 10, 24, 3, 31)


class DreamDueTest(unittest.TestCase):
    def test_before_dream_time_not_due(self):
        dream = DreamCycle(FakeStore(), conf(dream_time="03:30"))
        self.assertFalse(dream.due(datetime.datetime(2026, 10, 24, 3, 0)))

    def test_after_dream_time_due(self):
        dream = DreamCycle(FakeStore(), conf(dream_time="03:30"))
        self.assertTrue(dream.due(AT))

    def test_disabled_never_due(self):
        dream = DreamCycle(FakeStore(), conf(dream_enabled=False))
        self.assertFalse(dream.due(AT))


class DreamRunTest(unittest.IsolatedAsyncioTestCase):
    async def test_runs_once_and_is_idempotent(self):
        store, calls, left = FakeStore(), [], {"pending": 1}

        async def flush(_reason):
            calls.append(1)
            left["pending"] = 0
            return 2, 1

        dream = DreamCycle(store, conf())
        first = await dream.run(flush, pending=lambda: left["pending"], now=AT)
        second = await dream.run(flush, pending=lambda: left["pending"], now=AT)
        self.assertEqual(first.status, "done")
        self.assertEqual(first.written, 2)
        self.assertEqual(second.status, "skipped")
        self.assertEqual(second.reason, "not_due")
        self.assertEqual(len(calls), 1)

    async def test_failure_keeps_pending_for_resume(self):
        store = FakeStore()

        async def boom(_reason):
            raise RuntimeError("model down")

        dream = DreamCycle(store, conf())
        result = await dream.run(boom, pending=lambda: 3, now=AT)
        self.assertEqual(result.status, "failed")
        self.assertTrue(result.errors)
        # 失败后当天仍可续跑
        self.assertTrue(dream.due(AT))

        async def ok(_reason):
            return 1, 1

        again = await dream.run(ok, pending=lambda: 0, now=AT)
        self.assertEqual(again.status, "done")

    async def test_max_batches_bound(self):
        store, calls = FakeStore(), []

        async def flush(_reason):
            calls.append(1)
            return 0, 1

        dream = DreamCycle(store, conf(dream_max_batches=2))
        await dream.run(flush, pending=lambda: 99, now=AT)
        self.assertEqual(len(calls), 2)

    async def test_maintain_runs_after_flush(self):
        store, seen = FakeStore(), []

        async def flush(_reason):
            return 1, 1

        async def maintain():
            seen.append("maintain")
            return {"persona": True}

        dream = DreamCycle(store, conf())
        result = await dream.run(flush, pending=lambda: 0, maintain=maintain, now=AT)
        self.assertEqual(result.status, "done")
        self.assertEqual(result.summary.get("persona"), True)


class FlushPolicyDreamTest(unittest.TestCase):
    def test_dream_only_blocks_everything(self):
        decision = decide_flush(
            pending=100, idle_seconds=999, worth_now=True, flushes_today=0,
            idle_flush_seconds=0, min_pending=1, max_flushes_per_day=9,
            backlog_flush_at=1, topic_age_seconds=1e9, dream_only=True,
        )
        self.assertFalse(decision.should)
        self.assertEqual(decision.reason, "dream_only")


class BudgetTest(unittest.TestCase):
    def test_estimate_scales_with_chars(self):
        self.assertLess(estimate_tokens(800), estimate_tokens(1600))

    def test_budget_from_config(self):
        budget = budget_from_config(conf(budget_chars=900, group_context_messages=20))
        self.assertEqual(budget.injection_chars, 900)
        self.assertEqual(budget.group_context_messages, 20)
        self.assertGreater(budget.estimate_tokens, 0)

    def test_clamp_cuts_at_punctuation(self):
        text, size = clamp_chars("第一句话。第二句话。第三句话。", 12)
        self.assertTrue(text.endswith("。"))
        self.assertLessEqual(len(text), 12)
        self.assertEqual(size, len("第一句话。第二句话。第三句话。"))

    def test_default_budget(self):
        self.assertGreater(ContextBudget().estimate_tokens, 1000)

    def test_source_and_extraction_budgets_parse_zero_values(self):
        budget = budget_from_config(
            conf(
                source_context_enabled="false",
                source_context_tokens=0,
                source_context_min_free_tokens=0,
            )
        )
        self.assertFalse(budget.source_context_enabled)
        self.assertEqual(budget.source_context_chars, 0)
        self.assertEqual(budget.source_context_min_free_chars, 0)
        extraction = extraction_budget_from_config(
            conf(extraction_chunk_tokens=0, dream_token_budget=0)
        )
        self.assertEqual(extraction.extraction_chunk_tokens, 0)
        self.assertEqual(extraction.dream_token_budget, 0)
        self.assertEqual(ExtractionBudget().extraction_chunk_tokens, 2400)


class TokenChunkTest(unittest.TestCase):
    def test_chunks_respect_turn_and_token_limits_and_keep_pairs(self):
        parent = DialogueTurn("s", "u1", "user", "user " * 30, "", "s_user",
                              "", "t1")
        reply = DialogueTurn("s", "bot", "assistant", "reply " * 30, "",
                             "s_reply", "", "t1", "s_user")
        others = [
            DialogueTurn("s", "u1", "user", "other " * 30, "", f"o{index}",
                         "", f"ot{index}")
            for index in range(4)
        ]
        rows = [parent, reply, *others]
        chunks = chunk_turns(rows, limit=2, max_tokens=35)
        self.assertEqual([turn for chunk in chunks for turn in chunk], rows)
        self.assertTrue(all(len(chunk) <= 2 for chunk in chunks))
        pair_chunk = next(chunk for chunk in chunks if parent in chunk)
        self.assertIn(reply, pair_chunk)

    def test_token_chunks_never_drop_an_oversized_turn(self):
        rows = [
            DialogueTurn("s", "u1", "user", "oversized " * 100, "", "s1"),
            DialogueTurn("s", "u1", "user", "small", "", "s2"),
        ]
        chunks = chunk_turns(rows, limit=10, max_tokens=10)
        self.assertEqual([turn for chunk in chunks for turn in chunk], rows)
        self.assertIn(rows[0], chunks[0])


class DreamBudgetTest(unittest.IsolatedAsyncioTestCase):
    async def test_token_budget_stops_before_next_flush_and_still_maintains(self):
        store = FakeStore()
        usage = {"calls": 0, "in": 0, "cached": 0, "out": 0}
        calls = []
        maintained = []

        async def flush(_reason):
            calls.append(1)
            usage["calls"] += 1
            usage["in"] += 400
            usage["out"] += 200
            return 1, 1

        async def maintain():
            maintained.append(1)
            return {"persona": True}

        dream = DreamCycle(
            store,
            conf(dream_token_budget=1000, dream_max_batches=5),
        )
        result = await dream.run(
            flush,
            pending=lambda: 10,
            maintain=maintain,
            usage=lambda: dict(usage),
            now=AT,
        )
        self.assertEqual(len(calls), 2)
        self.assertEqual(maintained, [1])
        self.assertEqual(result.summary["budget"]["used"], 1200)
        self.assertEqual(result.summary["budget"]["stopped"], "token_budget")
        self.assertEqual(result.summary["usage"]["calls"], 2)
        self.assertEqual(result.summary["persona"], True)

    async def test_zero_budget_records_usage_without_stopping(self):
        store = FakeStore()
        usage = {"calls": 0, "in": 10, "cached": 0, "out": 5}
        calls = []

        async def flush(_reason):
            calls.append(1)
            usage["calls"] += 1
            usage["in"] += 10
            usage["out"] += 5
            return 1, 1

        dream = DreamCycle(
            store,
            conf(dream_token_budget=0, dream_max_batches=2),
        )
        result = await dream.run(
            flush,
            pending=lambda: 10,
            usage=lambda: dict(usage),
            now=AT,
        )
        self.assertEqual(len(calls), 2)
        self.assertEqual(result.summary["budget"]["stopped"], "")
        self.assertEqual(result.summary["usage"]["in"], 20)
        self.assertEqual(result.summary["usage"]["out"], 10)


if __name__ == "__main__":
    unittest.main()
