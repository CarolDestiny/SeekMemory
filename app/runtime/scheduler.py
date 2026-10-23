"""Pure scheduling policy for due wait, quiet and proactive runtime events.

The scheduler never sleeps, performs I/O, or reads a wall clock.  Callers pass a
:class:`SocialState` and the current timestamp, which keeps scheduling decisions
deterministic and straightforward to test with fakes.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from random import Random
from typing import Protocol

from .contracts import SocialState, WakeAction


class SchedulerEvent(str, Enum):
    WAIT = "wait"
    QUIET = "quiet"
    PROACTIVE = "proactive"


@dataclass(frozen=True)
class SchedulerDecision:
    """One event evaluation.

    ``due`` describes timing only.  For example, a wait with ``due=True`` has
    elapsed, while a proactive event can be due but skipped by probability.
    """

    event: SchedulerEvent
    action: WakeAction
    reason: str
    due: bool = False
    due_at: float = 0.0
    wait_seconds: float = 0.0
    confidence: float = 1.0


class RandomSource(Protocol):
    """Minimal injectable random source used by proactive decisions."""

    def random(self) -> float: ...


class SchedulerPolicy:
    """Deterministic policy over social state and an explicit clock value."""

    def __init__(self, cooldown_seconds: float | None = None) -> None:
        self.cooldown_seconds = cooldown_seconds

    def evaluate_wait(self, wait_until: float, now: float) -> SchedulerDecision:
        due_at = float(wait_until)
        moment = float(now)
        if moment >= due_at:
            return SchedulerDecision(
                event=SchedulerEvent.WAIT,
                action=WakeAction.OBSERVE,
                reason="wait_due",
                due=True,
                due_at=due_at,
            )
        return SchedulerDecision(
            event=SchedulerEvent.WAIT,
            action=WakeAction.WAIT,
            reason="wait_not_due",
            due=False,
            due_at=due_at,
            wait_seconds=due_at - moment,
        )

    def evaluate_quiet(self, state: SocialState, now: float) -> SchedulerDecision:
        due_at = float(state.quiet_until)
        moment = float(now)
        if due_at > moment:
            return SchedulerDecision(
                event=SchedulerEvent.QUIET,
                action=WakeAction.IGNORE,
                reason="quiet_window",
                due=False,
                due_at=due_at,
                wait_seconds=due_at - moment,
            )
        return SchedulerDecision(
            event=SchedulerEvent.QUIET,
            action=WakeAction.OBSERVE,
            reason="quiet_clear",
            due=True,
            due_at=due_at,
        )

    def cooldown_remaining(
        self,
        state: SocialState,
        now: float,
        cooldown_seconds: float | None = None,
    ) -> float:
        """Return seconds until another per-session action is allowed."""
        cooldown = self.cooldown_seconds
        if cooldown is None:
            cooldown = state.reply_cooldown_seconds
        cooldown = max(0.0, float(cooldown))
        if cooldown <= 0:
            return 0.0
        last_action_at = max(float(state.last_wake_at), float(state.last_spoke_at))
        if last_action_at <= 0:
            return 0.0
        return max(0.0, last_action_at + cooldown - float(now))

    def is_rate_limited(
        self,
        state: SocialState,
        now: float,
        cooldown_seconds: float | None = None,
    ) -> bool:
        return self.cooldown_remaining(state, now, cooldown_seconds) > 0.0

    def evaluate_proactive(
        self,
        state: SocialState,
        now: float,
        *,
        rng: RandomSource | None = None,
        seed: int | None = None,
        idle_seconds: float | None = None,
    ) -> SchedulerDecision:
        """Evaluate proactive timing, cooldown and probability.

        ``seed`` and ``rng`` are only used when the configured probability is
        between zero and one.  Supplying the same seed for the same state and
        timestamp always produces the same result.  When neither is supplied, a
        stable SHA-256-derived seed is used instead of Python's process-random
        ``hash()``.
        """
        moment = float(now)
        due_at = float(state.quiet_until)
        if due_at > moment:
            return SchedulerDecision(
                event=SchedulerEvent.PROACTIVE,
                action=WakeAction.IGNORE,
                reason="quiet_window",
                due=False,
                due_at=due_at,
                wait_seconds=due_at - moment,
            )

        remaining = self.cooldown_remaining(state, moment)
        if remaining > 0:
            return SchedulerDecision(
                event=SchedulerEvent.PROACTIVE,
                action=WakeAction.IGNORE,
                reason="rate_limited",
                due=False,
                due_at=moment + remaining,
                wait_seconds=remaining,
            )

        if idle_seconds is None:
            last_activity = max(
                float(state.last_seen_at),
                float(state.last_spoke_at),
                float(state.last_wake_at),
            )
            idle_seconds = max(0.0, moment - last_activity) if last_activity > 0 else 0.0
        idle = max(0.0, float(idle_seconds))
        threshold = max(0.0, float(state.proactive_idle_seconds))
        if idle < threshold:
            return SchedulerDecision(
                event=SchedulerEvent.PROACTIVE,
                action=WakeAction.OBSERVE,
                reason="not_idle_enough",
                due=False,
                due_at=moment + (threshold - idle),
                wait_seconds=threshold - idle,
            )

        probability = max(0.0, min(1.0, float(state.proactive_probability)))
        if probability <= 0.0:
            return SchedulerDecision(
                event=SchedulerEvent.PROACTIVE,
                action=WakeAction.OBSERVE,
                reason="proactive_disabled",
                due=True,
                confidence=0.0,
            )
        if probability >= 1.0:
            return SchedulerDecision(
                event=SchedulerEvent.PROACTIVE,
                action=WakeAction.PROACTIVE,
                reason="proactive_idle",
                due=True,
                confidence=1.0,
            )

        draw = self._draw(state.session_id, moment, seed=seed, rng=rng)
        if draw < probability:
            return SchedulerDecision(
                event=SchedulerEvent.PROACTIVE,
                action=WakeAction.PROACTIVE,
                reason="proactive_idle",
                due=True,
                confidence=probability,
            )
        return SchedulerDecision(
            event=SchedulerEvent.PROACTIVE,
            action=WakeAction.OBSERVE,
            reason="proactive_skip",
            due=True,
            confidence=probability,
        )

    def evaluate(
        self,
        state: SocialState,
        now: float,
        *,
        wait_until: float | None = None,
        rng: RandomSource | None = None,
        seed: int | None = None,
    ) -> tuple[SchedulerDecision, ...]:
        """Evaluate all applicable events without mutating state.

        ``wait_until`` is intentionally external to :class:`SocialState`; a
        host can keep its own pending-wait timestamp.  When omitted, a
        ``wait_until`` attribute on state is accepted for forward compatibility
        with state implementations that later persist it.
        """
        decisions = [self.evaluate_quiet(state, now)]
        deadline = wait_until
        if deadline is None:
            deadline = getattr(state, "wait_until", None)
        if deadline is not None and float(deadline) > 0:
            decisions.append(self.evaluate_wait(float(deadline), now))
        decisions.append(self.evaluate_proactive(state, now, rng=rng, seed=seed))
        return tuple(decisions)

    @staticmethod
    def _draw(
        session_id: str,
        now: float,
        *,
        seed: int | None = None,
        rng: RandomSource | None = None,
    ) -> float:
        if rng is not None:
            draw = float(rng.random())
        else:
            if seed is None:
                material = f"{session_id}:{int(now)}".encode("utf-8")
                seed = int.from_bytes(sha256(material).digest()[:8], "big")
            draw = Random(int(seed)).random()
        return max(0.0, min(1.0, draw))
