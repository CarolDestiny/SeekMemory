"""AstrBot implementation of runtime host actions."""

from __future__ import annotations


class AstrBotActionPort:
    """Send actions backed by the AstrBot host context."""

    def __init__(self, context, message_factory=None) -> None:
        self.context = context
        self.message_factory = message_factory

    def _chain(self, text: str):
        if self.message_factory is not None:
            return self.message_factory(text)
        from astrbot.core.message.message_event_result import MessageChain
        return MessageChain().message(text)

    async def send(self, session_id: str, text: str) -> bool:
        if not str(text or "").strip():
            return False
        result = await self.context.send_message(session_id, self._chain(text))
        return result is not False
