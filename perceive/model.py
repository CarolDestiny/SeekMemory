from __future__ import annotations

import asyncio
import time
from typing import Any

try:
    from ..app.contracts import ChatRequest, ChatResponse
except ImportError:
    from app.contracts import ChatRequest, ChatResponse


class ProviderChatModel:
    def __init__(self, provider: Any, timeout: float = 60.0) -> None:
        self.provider = provider
        self.timeout = float(timeout)

    async def complete(self, request: ChatRequest) -> ChatResponse:
        started = time.monotonic()
        kwargs = {}
        if request.model:
            kwargs["model"] = request.model
        resp = await asyncio.wait_for(
            self.provider.text_chat(
                system_prompt=request.system_prompt, prompt=request.prompt, **kwargs
            ),
            timeout=self.timeout,
        )
        usage = getattr(resp, "usage", None)
        meta = self.provider.meta() if hasattr(self.provider, "meta") else None
        return ChatResponse(
            text=str(getattr(resp, "completion_text", "") or ""),
            model=str(getattr(meta, "model", "") or ""),
            provider_id=str(getattr(meta, "id", "") or ""),
            usage_in=int(getattr(usage, "input", 0) or 0),
            usage_cached=int(getattr(usage, "input_cached", 0) or 0),
            usage_out=int(getattr(usage, "output", 0) or 0),
            response_id=str(getattr(resp, "id", "") or ""),
            latency_ms=int((time.monotonic() - started) * 1000),
        )
