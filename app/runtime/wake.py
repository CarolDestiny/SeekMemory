"""Pure wake policy: decide whether the bot should act on one inbound event."""

from __future__ import annotations

from .contracts import RuntimeInput, SocialState, WakeAction, WakeDecision


class WakePolicy:
    """Deterministic policy with no I/O and no AstrBot imports."""

    def evaluate(
        self, event: RuntimeInput, state: SocialState, now: float | None = None
    ) -> WakeDecision:
        moment = event.at or (now if now is not None else 0.0)
        text = str(event.text or "").strip()
        if not text:
            return WakeDecision(WakeAction.IGNORE, "empty_text")
        if state.wait_until > moment:
            return WakeDecision(
                WakeAction.WAIT,
                "waiting",
                wait_seconds=state.wait_until - moment,
            )
        if state.quiet_until > moment:
            return WakeDecision(WakeAction.IGNORE, "quiet_window")

        direct = event.mentioned or event.name_mentioned or event.reply_to_bot
        if direct:
            return WakeDecision(WakeAction.REPLY, "direct_attention", confidence=0.95)
        if event.question:
            return WakeDecision(WakeAction.REPLY, "question")
        if event.keyword_hit:
            return WakeDecision(WakeAction.REPLY, "keyword_match")

        cooldown_until = state.cooldown_until
        if not cooldown_until and state.last_spoke_at:
            cooldown_until = state.last_spoke_at + state.reply_cooldown_seconds
        if cooldown_until > moment:
            return WakeDecision(WakeAction.IGNORE, "reply_cooldown")

        return WakeDecision(WakeAction.OBSERVE, "ambient_message", confidence=0.5)

    def proactive(
        self, state: SocialState, idle_seconds: float, now: float, seed: int = 0
    ) -> WakeDecision:
        """Offline-friendly proactive decision with deterministic sampling."""
        if idle_seconds < state.proactive_idle_seconds:
            return WakeDecision(WakeAction.OBSERVE, "not_idle_enough")
        if state.quiet_until > now:
            return WakeDecision(WakeAction.IGNORE, "quiet_window")
        probability = max(0.0, min(1.0, float(state.proactive_probability)))
        if probability <= 0:
            return WakeDecision(WakeAction.OBSERVE, "proactive_disabled")
        # A stable pseudo-random draw: one path per session/minute.
        draw = (abs(hash((state.session_id, int(now), int(seed)))) % 10_000) / 10_000
        if draw >= probability:
            return WakeDecision(WakeAction.OBSERVE, "proactive_skip")
        return WakeDecision(WakeAction.PROACTIVE, "proactive_idle", confidence=probability)
