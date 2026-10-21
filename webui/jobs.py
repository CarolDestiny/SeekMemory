"""串行执行定时与手动维护，记录明确的生命周期事件。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from uuid import uuid4

from .journal import Journal


class Jobs:
    """管理唯一的活动维护任务，并在插件停止时取消。"""

    def __init__(self, journal: Journal) -> None:
        self.journal = journal
        self.task: asyncio.Task[None] | None = None
        self.task_id = ""
        self.kind = ""
        self.closed = False

    def submit(self, kind: str, operation: Callable[[], Awaitable[None]]) -> str:
        """调度操作，拒绝并行维护及停止期间的新任务。

        Args:
            kind: 操作名称。
            operation: 延迟执行的操作，复用插件运行中的引擎。

        Returns:
            生命周期日志中可见的任务关联 ID。

        Raises:
            RuntimeError: 执行器忙碌或正在停止。
        """
        if self.closed or self.task is not None and not self.task.done():
            raise RuntimeError("维护任务正在运行或停止")
        task_id = uuid4().hex
        self.task_id, self.kind = task_id, kind
        self.journal.record(kind, "queued", "任务已接收", task_id)

        async def execute() -> None:
            token = self.journal.task_id.set(task_id)
            self.journal.record(kind, "running", "任务已开始", task_id)
            try:
                await operation()
            except asyncio.CancelledError:
                self.journal.record(kind, "cancelled", "任务已取消", task_id)
                raise
            except Exception as exc:
                self.journal.record(kind, "failed", "任务失败", task_id, error=exc)
            else:
                self.journal.record(kind, "succeeded", "任务已完成", task_id)
            finally:
                self.journal.task_id.reset(token)

        self.task = asyncio.create_task(execute(), name=f"seekmemory-{kind}")

        def finalize(task: asyncio.Task[None]) -> None:
            if task.cancelled() and not any(
                event["taskId"] == task_id and event["status"] == "cancelled"
                for event in self.journal.events
            ):
                self.journal.record(kind, "cancelled", "任务在执行前已取消", task_id)

        self.task.add_done_callback(finalize)
        return task_id

    async def close(self) -> None:
        """停止接收任务，等待取消完成后再关闭数据库。"""
        self.closed = True
        if self.task is not None and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
