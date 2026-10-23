"""Bridge the runtime MemoryContextPort to SeekMemory's recall pipeline."""

from __future__ import annotations

from typing import Callable

try:
    from ..app.runtime.contracts import MemoryContext, RuntimeInput
except ImportError:
    from app.runtime.contracts import MemoryContext, RuntimeInput


class SeekMemoryContextAdapter:
    def __init__(self, build: Callable[[RuntimeInput], MemoryContext]) -> None:
        self._build = build

    def build_context(self, event: RuntimeInput) -> MemoryContext:
        return self._build(event)
