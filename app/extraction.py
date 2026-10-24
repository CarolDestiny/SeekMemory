"""抽取批次用例：选择话题、处理重试，并在成功后确认待抽取消息。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from .contracts import DialogueTurn, WriteOutcome
from .flush_policy import chunk_turns, select_topic_batches
from .ports import ChatModel, ExtractionStore


@dataclass(frozen=True)
class PreparedTopic:
    session_id: str
    topic_id: str
    turns: list[DialogueTurn]
    model: ChatModel


class ExtractionService:
    """Own the complete batch lifecycle without depending on the host or model SDK."""

    def __init__(
        self, *, db: ExtractionStore | None, buffer: Any,
        resolve_model: Callable[[str], Awaitable[ChatModel | None]],
        extract: Callable[..., Awaitable[WriteOutcome]], journal: Any,
        max_attempts: int = 5,
    ) -> None:
        self.db = db
        self.buffer = buffer
        self.resolve_model = resolve_model
        self.extract = extract
        self.journal = journal
        self.max_attempts = max_attempts
        self.running = False
        self.day = ""
        self.count = 0

    async def run(self, reason: str, limit: int) -> tuple[int, int]:
        """Keep failed, cancelled and newly arrived input available for a later batch."""
        if self.running or self.buffer is None or not self.buffer.items or self.db is None:
            return 0, 0
        self.running = True
        try:
            topics = select_topic_batches(list(self.buffer.items), limit)
            ready_ids = self.db.ready_extraction_ids()
            ready: list[PreparedTopic] = []
            failure: Exception | None = None
            for session, topic, part in topics:
                part = [turn for turn in part
                        if not turn.source_id or turn.source_id in ready_ids]
                if not part:
                    continue
                try:
                    with self.journal.span(
                        "extract", "provider.resolve", session=session, topic=topic,
                    ):
                        model = await self.resolve_model(session)
                except Exception as exc:
                    self.buffer.mark_failed(part, type(exc).__name__,
                                            max_attempts=self.max_attempts)
                    failure = failure or exc
                    continue
                if model is None:
                    self.journal.record(
                        "extract", "warning", "该会话尚未配置模型服务，保留待抽取消息",
                        stage="provider.resolve", context={"session": session, "topic": topic},
                    )
                    continue
                ready.append(PreparedTopic(session, topic, part, model))
            if not ready:
                if failure is not None:
                    raise failure
                return 0, 0
            self.count += 1
            written = 0
            for topic in ready:
                for chunk in chunk_turns(topic.turns):
                    try:
                        with self.journal.span(
                            "extract", "topic.extract", session=topic.session_id,
                            topic=topic.topic_id, messages=len(chunk),
                        ) as metrics:
                            outcome = await self.extract(chunk, model=topic.model)
                            metrics["written"] = outcome.written
                            metrics["skipped"] = outcome.skipped
                            if outcome.model_failed or outcome.retryable:
                                raise RuntimeError("extraction failed; keep pending input")
                    except Exception as exc:
                        self.buffer.mark_failed(chunk, type(exc).__name__,
                                                max_attempts=self.max_attempts)
                        failure = failure or exc
                        break
                    self.buffer.mark_succeeded(chunk)
                    written += outcome.written
            self.journal.record(
                "extract", "info", f"已尝试 {len(ready)} 个话题，写入 {written} 条记忆",
                context={"topics": len(ready), "written": written}, stage="batch.complete",
            )
            if failure is not None:
                raise failure
            return written, len(ready)
        finally:
            self.running = False
