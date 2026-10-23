"""Pure runtime scheduler tests; no asyncio, AstrBot or database dependencies."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.runtime import (  # noqa: E402
    SocialState,
    SchedulerEvent,
    SchedulerPolicy,
    WakeAction,
)


class FixedRandom:
    def __init__(self, value: float) -> None:
        self.value = value

    def random(self) -> float:
        return self.value


class SchedulerPolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = SchedulerPolicy()

    def test_wait_not_due_then_due(self) -> None:
        waiting = self.policy.evaluate_wait(wait_until=125.0, now=100.0)
        self.assertFalse(waiting.due)
        self.assertEqual(waiting.event, SchedulerEvent.WAIT)
        self.assertEqual(waiting.action, WakeAction.WAIT)
        self.assertEqual(waiting.wait_seconds, 25.0)

        due = self.policy.evaluate_wait(wait_until=125.0, now=125.0)
        self.assertTrue(due.due)
        self.assertEqual(due.reason, "wait_due")
        self.assertEqual(due.action, WakeAction.OBSERVE)
        self.assertEqual(due.wait_seconds, 0.0)

    def test_quiet_window_suppresses_actions_until_it_expires(self) -> None:
        state = SocialState(session_id="s1", quiet_until=150.0)
        active = self.policy.evaluate_quiet(state, now=120.0)
        self.assertFalse(active.due)
        self.assertEqual(active.action, WakeAction.IGNORE)
        self.assertEqual(active.reason, "quiet_window")
        self.assertEqual(active.wait_seconds, 30.0)

        clear = self.policy.evaluate_quiet(state, now=150.0)
        self.assertTrue(clear.due)
        self.assertEqual(clear.action, WakeAction.OBSERVE)
        self.assertEqual(clear.reason, "quiet_clear")

    def test_proactive_probability_zero_skips(self) -> None:
        state = SocialState(
            session_id="s1",
            last_seen_at=100.0,
            proactive_idle_seconds=60.0,
            proactive_probability=0.0,
        )
        decision = self.policy.evaluate_proactive(state, now=1000.0, seed=7)
        self.assertTrue(decision.due)
        self.assertEqual(decision.action, WakeAction.OBSERVE)
        self.assertEqual(decision.reason, "proactive_disabled")

    def test_proactive_probability_one_always_fires(self) -> None:
        state = SocialState(
            session_id="s1",
            last_seen_at=100.0,
            proactive_idle_seconds=60.0,
            proactive_probability=1.0,
        )
        decision = self.policy.evaluate_proactive(state, now=1000.0, seed=7)
        self.assertTrue(decision.due)
        self.assertEqual(decision.action, WakeAction.PROACTIVE)
        self.assertEqual(decision.reason, "proactive_idle")

    def test_proactive_respects_idle_threshold_and_quiet_window(self) -> None:
        state = SocialState(
            session_id="s1",
            last_seen_at=100.0,
            quiet_until=500.0,
            proactive_idle_seconds=60.0,
            proactive_probability=1.0,
        )
        quiet = self.policy.evaluate_proactive(state, now=200.0)
        self.assertEqual(quiet.action, WakeAction.IGNORE)
        self.assertEqual(quiet.reason, "quiet_window")

        state.quiet_until = 0.0
        early = self.policy.evaluate_proactive(state, now=120.0)
        self.assertFalse(early.due)
        self.assertEqual(early.action, WakeAction.OBSERVE)
        self.assertEqual(early.reason, "not_idle_enough")
        self.assertEqual(early.wait_seconds, 40.0)

    def test_per_session_rate_limit_blocks_proactive(self) -> None:
        state = SocialState(
            session_id="s1",
            last_seen_at=900.0,
            last_wake_at=990.0,
            proactive_idle_seconds=60.0,
            proactive_probability=1.0,
            reply_cooldown_seconds=30.0,
        )
        self.assertTrue(self.policy.is_rate_limited(state, now=1000.0))
        self.assertEqual(self.policy.cooldown_remaining(state, now=1000.0), 20.0)
        decision = self.policy.evaluate_proactive(state, now=1000.0)
        self.assertEqual(decision.action, WakeAction.IGNORE)
        self.assertEqual(decision.reason, "rate_limited")
        self.assertFalse(self.policy.is_rate_limited(state, now=1020.0))

    def test_seeded_proactive_decision_is_deterministic(self) -> None:
        state = SocialState(
            session_id="s1",
            last_seen_at=100.0,
            proactive_idle_seconds=60.0,
            proactive_probability=0.5,
        )
        first = self.policy.evaluate_proactive(state, now=1000.0, seed=123)
        second = self.policy.evaluate_proactive(state, now=1000.0, seed=123)
        self.assertEqual(first, second)

    def test_injectable_random_source_controls_probability(self) -> None:
        state = SocialState(
            session_id="s1",
            last_seen_at=100.0,
            proactive_idle_seconds=60.0,
            proactive_probability=0.5,
        )
        fires = self.policy.evaluate_proactive(
            state, now=1000.0, rng=FixedRandom(0.1)
        )
        skips = self.policy.evaluate_proactive(
            state, now=1000.0, rng=FixedRandom(0.9)
        )
        self.assertEqual(fires.action, WakeAction.PROACTIVE)
        self.assertEqual(skips.action, WakeAction.OBSERVE)
        self.assertEqual(skips.reason, "proactive_skip")

    def test_evaluate_returns_stable_event_order(self) -> None:
        state = SocialState(
            session_id="s1",
            last_seen_at=100.0,
            quiet_until=0.0,
            proactive_idle_seconds=60.0,
            proactive_probability=1.0,
        )
        decisions = self.policy.evaluate(state, now=1000.0, wait_until=900.0)
        self.assertEqual(
            [decision.event for decision in decisions],
            [SchedulerEvent.QUIET, SchedulerEvent.WAIT, SchedulerEvent.PROACTIVE],
        )
        self.assertEqual(decisions[1].reason, "wait_due")
        self.assertEqual(decisions[2].action, WakeAction.PROACTIVE)

    def test_scheduler_module_has_no_host_or_io_dependencies(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "app" / "runtime" / "scheduler.py"
        ).read_text(encoding="utf-8")
        for forbidden in ("import asyncio", "import astrbot", "from astrbot",
                          "import sqlite3", "from .state", "from .runtime"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
