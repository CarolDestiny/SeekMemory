"""Bounded business events with source locations and task correlation."""

from __future__ import annotations

import asyncio
import inspect
import json
from collections import deque
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from types import FrameType
from uuid import uuid4

Scalar = str | int | float | bool | None
_ROOT = Path(__file__).resolve().parents[1]


def _location(frame: FrameType, line: int) -> dict:
    """Describe a frame without capturing locals or absolute installation paths.

    Args:
        frame: Caller or exception frame.
        line: Line at which the event or exception occurred.

    Returns:
        Module, relative filename, function and one-based line number.
    """
    path = Path(frame.f_code.co_filename).resolve()
    return {
        "module": str(frame.f_globals.get("__name__", "unknown")),
        "file": path.relative_to(_ROOT).as_posix()
        if path.is_relative_to(_ROOT)
        else path.name,
        "function": frame.f_code.co_name,
        "line": line,
    }


class Journal:
    """Persist bounded events and expose reusable business-stage instrumentation."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.events: deque[dict] = deque(maxlen=500)
        self.task_id: ContextVar[str] = ContextVar("seekmemory_task_id", default="")
        self.persistence_error = False
        try:
            for file in (path.with_suffix(".jsonl.1"), path):
                if file.exists():
                    with file.open("rb") as stream:
                        stream.seek(max(0, file.stat().st_size - 1024 * 1024))
                        for line in stream.read().splitlines():
                            try:
                                row = json.loads(line)
                                if isinstance(row, dict) and all(
                                    isinstance(row.get(key), str)
                                    for key in (
                                        "id",
                                        "at",
                                        "kind",
                                        "status",
                                        "message",
                                        "taskId",
                                    )
                                ):
                                    # Old events remain valid; their source location is unknown.
                                    self.events.append(row)
                            except (ValueError, UnicodeError):
                                continue
        except OSError:
            self.persistence_error = True
        unfinished: dict[str, dict] = {}
        for event in self.events:
            if (
                event["taskId"]
                and not event.get("stage")
                and event["status"]
                in {
                    "queued",
                    "running",
                    "succeeded",
                    "failed",
                    "cancelled",
                    "interrupted",
                }
            ):
                unfinished[event["taskId"]] = event
        for task_id, event in unfinished.items():
            if event["status"] in {"queued", "running"}:
                self.record(
                    event["kind"], "interrupted", "Previous process stopped", task_id
                )

    def record(
        self,
        kind: str,
        status: str,
        message: str,
        task_id: str = "",
        *,
        stage: str = "",
        context: Mapping[str, Scalar] | None = None,
        duration_ms: float | None = None,
        error: BaseException | None = None,
        source: dict | None = None,
    ) -> None:
        """Append a structured event without exposing exception text or locals.

        Args:
            kind: Business operation category.
            status: Lifecycle state or severity.
            message: Static operational summary; never pass conversation content.
            task_id: Explicit correlation ID, otherwise inherited from the task.
            stage: Stable business-stage name, independent of lifecycle status.
            context: Explicit scalar IDs and counters, never payloads or credentials.
            duration_ms: Optional elapsed stage time.
            error: Exception whose type and frame locations may be recorded.
            source: Captured call site for a stage wrapper, otherwise the direct caller.
        """
        frame = inspect.currentframe()
        try:
            if source is None and frame is not None and frame.f_back is not None:
                source = _location(frame.f_back, frame.f_back.f_lineno)
        finally:
            del frame
        failure = None
        if error is not None:
            frames = []
            tb = error.__traceback__
            while tb is not None:
                frames.append(_location(tb.tb_frame, tb.tb_lineno))
                tb = tb.tb_next
            failure = {"type": type(error).__name__, "frames": frames[-12:]}
        level = (
            "ERROR"
            if status == "failed"
            else (
                "WARNING"
                if status in {"warning", "cancelled", "interrupted"}
                else ("DEBUG" if status == "debug" else "INFO")
            )
        )
        row = {
            "id": uuid4().hex,
            "at": datetime.now(timezone.utc).isoformat(),
            "kind": kind,
            "status": status,
            "message": message[:1000],
            "taskId": task_id or self.task_id.get(),
            "level": level,
            "stage": stage,
            "source": source,
            "context": {
                str(key)[:80]: value[:200] if isinstance(value, str) else value
                for key, value in list((context or {}).items())[:32]
                if value is None or type(value) in (str, int, float, bool)
            },
            "durationMs": duration_ms,
            "error": failure,
        }
        self.events.append(row)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists() and self.path.stat().st_size > 1024 * 1024:
                self.path.replace(self.path.with_suffix(".jsonl.1"))
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            self.persistence_error = False
        except OSError:
            self.persistence_error = True

    @contextmanager
    def span(
        self, kind: str, stage: str, **context: Scalar
    ) -> Iterator[dict[str, Scalar]]:
        """Trace a synchronous or awaited business stage and preserve its failures.

        Args:
            kind: Business operation category.
            stage: Stable stage name shown in the log viewer.
            **context: Explicit safe counters and IDs; yielded context accepts results.

        Yields:
            Mutable scalar context for recording stage outcome counters.

        Raises:
            BaseException: The original operation failure or cancellation, unchanged.
        """
        frame = inspect.currentframe()
        try:
            caller = frame.f_back if frame else None
            # contextlib enters this generator; report the user's with statement.
            while caller and caller.f_globals.get("__name__") == "contextlib":
                caller = caller.f_back
            source = _location(caller, caller.f_lineno) if caller else None
        finally:
            del frame
            del caller
        self.record(
            kind,
            "running",
            "Stage started",
            stage=stage,
            context=context,
            source=source,
        )
        start = perf_counter()
        try:
            yield context
        except BaseException as exc:
            self.record(
                kind,
                "cancelled" if isinstance(exc, asyncio.CancelledError) else "failed",
                "Stage interrupted",
                stage=stage,
                context=context,
                duration_ms=round((perf_counter() - start) * 1000, 2),
                error=exc,
                source=source,
            )
            raise
        else:
            self.record(
                kind,
                "succeeded",
                "Stage completed",
                stage=stage,
                context=context,
                duration_ms=round((perf_counter() - start) * 1000, 2),
                source=source,
            )
