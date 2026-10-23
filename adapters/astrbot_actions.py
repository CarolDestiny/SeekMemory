"""AstrBot implementation of runtime host actions."""

from __future__ import annotations

import asyncio


class AstrBotActionPort:
    """Send/wait actions backed by the AstrBot host context."""

    def __init__(self, context, message_factory=None) -> None:
        self.context = context
        self.message_factory = message_factory

    def _chain(self, text: str):
        if self.message_factory is not None:
            return self.message_factory(text)
        from astrbot.core.message.message_event_result import MessageChain
        return MessageChain().message(text)

    async def send(self, session_id: str, text: str) -> None:
        if not str(text or "").strip():
            return
        await self.context.send_message(session_id, self._chain(text))

    async def proactive(self, session_id: str, text: str) -> None:
        await self.send(session_id, text)

    async def wait(self, seconds: float) -> None:
        await asyncio.sleep(max(0.0, float(seconds)))
