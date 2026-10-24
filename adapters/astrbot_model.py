"""AstrBot implementation of the runtime model gateway."""

from __future__ import annotations


class AstrBotModelGateway:
    """Resolve the host provider for a session and return completion text."""

    def __init__(self, context) -> None:
        self.context = context

    async def complete(
        self, session_id: str, prompt: str, system_prompt: str | None = None
    ) -> str:
        provider = await self.context.get_using_provider_async(session_id)
        if provider is None:
            raise RuntimeError("no_provider")
        response = await provider.text_chat(
            prompt=str(prompt or ""),
            system_prompt=system_prompt or None,
        )
        return str(getattr(response, "completion_text", "") or "").strip()
