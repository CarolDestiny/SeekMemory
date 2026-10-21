"""Serialize scheduled and manual maintenance with explicit lifecycle events."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from uuid import uuid4

from .journal import Journal


class Jobs:
    """Own one active maintenance task and cancel it during plugin shutdown."""

    def __init__(self, journal: Journal) -> None:
        self.journal = journal
        self.task: asyncio.Task[None] | None = None
        self.task_id = ""
        self.kind = ""
        self.closed = False

    def submit(self, kind: str, operation: Callable[[], Awaitable[None]]) -> str:
        """Schedule an operation, rejecting overlapping or shutdown work.

        Args:
            kind: Operation name.
            operation: Deferred operation sharing the plugin's live engine.

        Returns:
            Correlation ID visible in the lifecycle log.

        Raises:
            RuntimeError: If the runner is busy or shutting down.
        """
        if self.closed or self.task is not None and not self.task.done():
            raise RuntimeError("Maintenance is busy or stopping")
        task_id = uuid4().hex
        self.task_id, self.kind = task_id, kind
        self.journal.record(kind, "queued", "Task accepted", task_id)

        async def execute() -> None:
            self.journal.record(kind, "running", "Task started", task_id)
            try:
                await operation()
            except asyncio.CancelledError:
                self.journal.record(kind, "cancelled", "Task cancelled", task_id)
                raise
            except Exception as exc:
                self.journal.record(kind, "failed", type(exc).__name__, task_id)
            else:
                self.journal.record(kind, "succeeded", "Task completed", task_id)

        self.task = asyncio.create_task(execute(), name=f"seekmemory-{kind}")

        def finalize(task: asyncio.Task[None]) -> None:
            if task.cancelled() and not any(
                event["taskId"] == task_id and event["status"] == "cancelled"
                for event in self.journal.events
            ):
                self.journal.record(
                    kind, "cancelled", "Task cancelled before execution", task_id
                )

        self.task.add_done_callback(finalize)
        return task_id

    async def close(self) -> None:
        """Stop accepting work and await cancellation before closing the database."""
        self.closed = True
        if self.task is not None and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
