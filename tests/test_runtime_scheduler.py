"""TimingPolicy and Scheduler due-selection tests."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.runtime import DueRun, Scheduler, SocialState, TimingPolicy  # noqa: E402


class Store:
    def __init__(self, states):
        self.states = states

    def get(self, session_id):
        if session_id == "broken":
            raise RuntimeError("broken state")
        return self.states.get(session_id, SocialState(session_id=session_id))

    def put(self, state):
        self.states[state.session_id] = state


class TimingPolicyTest(unittest.TestCase):
    def setUp(self):
        self.policy = TimingPolicy()

    def test_wait_due(self):
        state = SocialState("s1", wait_until=100)
        self.assertEqual(
            self.policy.evaluate(state, 100),
            DueRun("s1", "wait", 100),
        )

    def test_retry_due(self):
        state = SocialState("s1", wait_until=100, next_retry_at=100)
        self.assertEqual(
            self.policy.evaluate(state, 101),
            DueRun("s1", "retry", 100),
        )

    def test_retry_only_due(self):
        state = SocialState("s1", next_retry_at=80)
        self.assertEqual(
            self.policy.evaluate(state, 100),
            DueRun("s1", "retry", 80),
        )

    def test_not_due(self):
        state = SocialState("s1", wait_until=200, next_retry_at=300)
        self.assertIsNone(self.policy.evaluate(state, 100))

    def test_scheduler_isolates_broken_sessions(self):
        store = Store({
            "s1": SocialState("s1", wait_until=100),
            "s2": SocialState("s2", wait_until=300),
        })
        due = Scheduler(store).due(["s1", "broken", "s2"], 150)
        self.assertEqual(due, (DueRun("s1", "wait", 100),))


if __name__ == "__main__":
    unittest.main()
