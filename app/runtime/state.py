"""Social state stores for the runtime."""

from __future__ import annotations

from .contracts import SocialState


class InMemoryStateStore:
    """Small deterministic store used by tests and the first observe-only phase."""

    def __init__(self) -> None:
        self._items: dict[str, SocialState] = {}

    def get(self, session_id: str) -> SocialState:
        key = str(session_id or "")
        state = self._items.get(key)
        if state is None:
            state = SocialState(session_id=key)
            self._items[key] = state
        return state

    def put(self, state: SocialState) -> None:
        self._items[str(state.session_id or "")] = state
