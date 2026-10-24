"""TimingPolicy and Scheduler due-selection tests."""

from __future__ import annotations

import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.runtime import (  # noqa: E402
    DueRun,
    InMemoryStateStore,
    RunContext,
    RuntimeWorker,
    Scheduler,
    SessionState,
    TimingPolicy,
)


class Store:
    def __init__(self, states):
        self.states = states

    def get(self, session_id):
        if session_id == "broken":
            raise RuntimeError("broken state")
        return self.states.get(session_id, SessionState(session_id=session_id))

    def put(self, state):
        self.states[state.session_id] = state


class TimingPolicyTest(unittest.TestCase):
    def setUp(self):
        self.policy = TimingPolicy()

    def test_wait_due(self):
        state = SessionState("s1", wait_until=100)
        self.assertEqual(
            self.policy.evaluate(state, 100),
            DueRun("s1", "wait", 100),
        )

    def test_retry_due(self):
        state = SessionState("s1", wait_until=100, next_retry_at=100)
        self.assertEqual(
            self.policy.evaluate(state, 101),
            DueRun("s1", "retry", 100),
        )

    def test_retry_only_due(self):
        state = SessionState("s1", next_retry_at=80)
        self.assertEqual(
            self.policy.evaluate(state, 100),
            DueRun("s1", "retry", 80),
        )

    def test_not_due(self):
        state = SessionState("s1", wait_until=200, next_retry_at=300)
        self.assertIsNone(self.policy.evaluate(state, 100))

    def test_scheduler_isolates_broken_sessions(self):
        store = Store({
            "s1": SessionState("s1", wait_until=100),
            "s2": SessionState("s2", wait_until=300),
        })
        due = Scheduler(store).due(["s1", "broken", "s2"], 150)
        self.assertEqual(due, (DueRun("s1", "wait", 100),))


class RuntimeWorkerTest(unittest.TestCase):
    def _worker(self, enabled=True):
        class Runtime:
            def __init__(self):
                self.contexts = []

            async def dispatch_deferred(self, context, **kwargs):
                self.contexts.append((context, kwargs))
                return None

        store = InMemoryStateStore()
        state = store.get("s1")
        state.wait_until = 100
        store.put(state)
        runtime = Runtime()
        worker = RuntimeWorker(
            runtime=runtime,
            scheduler=Scheduler(store),
            enabled=lambda: enabled,
            session_ids=lambda limit: ["s1"],
            run_context=lambda session_id, now: RunContext(
                session_id=session_id, text="hello", at=now
            ),
            interval_seconds=lambda: 1,
            max_attempts=lambda: 3,
            base_seconds=lambda: 2,
        )
        return worker, runtime

    def test_due_session_dispatches_through_runtime(self) -> None:
        worker, runtime = self._worker()
        dispatched = asyncio.run(worker.tick(now=100))
        self.assertEqual(dispatched, 1)
        self.assertEqual(runtime.contexts[0][0].session_id, "s1")

    def test_gate_off_is_a_hard_no_op(self) -> None:
        worker, runtime = self._worker(enabled=False)
        self.assertEqual(asyncio.run(worker.tick(now=100)), 0)
        self.assertIsNone(asyncio.run(worker.dispatch("s1", 100)))
        self.assertEqual(runtime.contexts, [])


if __name__ == "__main__":
    unittest.main()
