"""Pure wake policy: decide whether the bot should act on one inbound event."""

from __future__ import annotations

from .contracts import (
    AttentionLevel,
    RuntimeInput,
    SocialState,
    WakeAction,
    WakeDecision,
)


class WakePolicy:
    """Deterministic policy with no I/O and no AstrBot imports.

    ``wait`` is a defer for ambient group traffic, never a mute for private
    messages or direct attention. Private messages and @/reply-to-bot are hard
    attention and must keep a reply path.
    """

    def evaluate(
        self, event: RuntimeInput, state: SocialState, now: float | None = None
    ) -> WakeDecision:
        moment = event.at or (now if now is not None else 0.0)
        text = str(event.text or "").strip()
        if not text:
            return WakeDecision(WakeAction.IGNORE, "empty_text")

        if event.private:
            return WakeDecision(
                WakeAction.REPLY,
                "private_message",
                attention=AttentionLevel.PRIVATE,
                must_reply=True,
                confidence=1.0,
            )

        direct = event.mentioned or event.reply_to_bot
        if direct:
            return WakeDecision(
                WakeAction.REPLY,
                "direct_attention",
                attention=AttentionLevel.DIRECT,
                must_reply=True,
                confidence=0.95,
            )

        if state.quiet_until > moment:
            return WakeDecision(
                WakeAction.IGNORE,
                "quiet_window",
                attention=AttentionLevel.AMBIENT,
            )

        if event.name_mentioned:
            return WakeDecision(
                WakeAction.REPLY,
                "name_mentioned",
                attention=AttentionLevel.ADDRESSED,
                confidence=0.8,
            )
        if event.question:
            return WakeDecision(
                WakeAction.REPLY,
                "question",
                attention=AttentionLevel.ADDRESSED,
                confidence=0.7,
            )
        if event.keyword_hit:
            return WakeDecision(
                WakeAction.REPLY,
                "keyword_match",
                attention=AttentionLevel.ADDRESSED,
                confidence=0.7,
            )

        if state.wait_until > moment:
            return WakeDecision(
                WakeAction.WAIT,
                "waiting",
                attention=AttentionLevel.AMBIENT,
                wait_seconds=state.wait_until - moment,
                defer_until=state.wait_until,
            )

        cooldown_until = state.cooldown_until
        if not cooldown_until and state.last_spoke_at:
            cooldown_until = state.last_spoke_at + state.reply_cooldown_seconds
        if cooldown_until > moment:
            return WakeDecision(
                WakeAction.IGNORE,
                "reply_cooldown",
                attention=AttentionLevel.AMBIENT,
            )

        return WakeDecision(
            WakeAction.OBSERVE,
            "ambient_message",
            attention=AttentionLevel.AMBIENT,
            confidence=0.5,
        )
