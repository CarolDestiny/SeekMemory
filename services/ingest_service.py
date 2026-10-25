"""Pending-buffer extraction service."""

from __future__ import annotations

import datetime
from functools import partial
from typing import Any, Awaitable, Callable

try:
    from ..app.flush_policy import chunk_turns, decide_flush, select_topic_batches
    from ..core.capacity import PROTECTIVE, SATURATED
    from ..perceive.absorb import absorb, worth_now
    from ..perceive.model import ProviderChatModel
    from ..app.ports import ArtifactStore, ExtractionStore, SourceStore
except ImportError:
    from app.flush_policy import chunk_turns, decide_flush, select_topic_batches
    from core.capacity import PROTECTIVE, SATURATED
    from perceive.absorb import absorb, worth_now
    from perceive.model import ProviderChatModel
    from app.ports import ArtifactStore, ExtractionStore, SourceStore


class IngestService:
    """Turn pending dialogue into memory; never owns capacity or scheduling."""

    def __init__(
        self,
        *,
        buffer: Any,
        artifacts: ArtifactStore | None,
        sources: SourceStore | None,
        extraction: ExtractionStore | None,
        cache: Any,
        graph: Any,
        journal,
        config: Callable[[str, Any], Any],
        provider_for: Callable[[str | None], Awaitable[Any]],
        owner_id: Callable[[], str],
        logger,
    ) -> None:
        self.buffer = buffer
        self.artifacts = artifacts
        self.sources = sources
        self.extraction = extraction
        self.cache = cache
        self.graph = graph
        self.journal = journal
        self.config = config
        self.provider_for = provider_for
        self.owner_id = owner_id
        self.logger = logger
        self.flushing = False
        self.flush_day = ""
        self.flush_count = 0

    def should_flush(
        self,
        *,
        capacity_state: str,
        capacity_actions,
        dream_only: bool,
    ) -> bool:
        if self.flushing or self.buffer is None or self.extraction is None:
            return False
        today = datetime.date.today().isoformat()
        if self.flush_day != today:
            self.flush_day, self.flush_count = today, 0
        decision = decide_flush(
            pending=len(self.buffer.items),
            idle_seconds=self.buffer.idle_seconds(),
            worth_now=worth_now(self.buffer.items),
            flushes_today=self.flush_count,
            idle_flush_seconds=float(self.config("idle_flush_seconds", 0)),
            min_pending=int(self.config("min_pending", 8)),
            max_flushes_per_day=int(self.config("max_flushes_per_day", 2)),
            backlog_flush_at=int(self.config("backlog_flush_at", 30)),
            topic_age_seconds=self.buffer.oldest_topic_age(),
            topic_ttl_seconds=float(self.config("topic_ttl_seconds", 86400)),
            dream_only=dream_only,
        )
        if decision.should:
            return True
        if dream_only:
            return False
        return (
            capacity_state in (SATURATED, PROTECTIVE)
            and "schedule_extraction" in set(capacity_actions)
        )

    def split_topics(self, items, cap: int | None = None):
        return select_topic_batches(
            items,
            int(cap or self.config("max_sessions_per_flush", 6)),
        )

    async def flush(
        self,
        reason: str,
        *,
        limit: int = 0,
        batch_cap: int = 6,
        max_attempts: int = 5,
    ) -> tuple[int, int]:
        """Extract ready topics while preserving pending rows on failure."""
        if (
            self.flushing
            or self.buffer is None
            or not self.buffer.items
            or self.extraction is None
        ):
            return 0, 0
        self.flushing = True
        try:
            topics = self.split_topics(
                list(self.buffer.items),
                cap=limit or batch_cap,
            )
            ready_ids = self.extraction.ready_extraction_ids()
            ready = []
            failure: Exception | None = None
            for session_id, topic_id, part in topics:
                part = [
                    turn
                    for turn in part
                    if not turn.source_id or turn.source_id in ready_ids
                ]
                if not part:
                    continue
                try:
                    with self.journal.span(
                        "extract",
                        "provider.resolve",
                        session=session_id,
                        topic=topic_id,
                    ):
                        provider = await self.provider_for(session_id or None)
                except Exception as exc:
                    self.buffer.mark_failed(part, type(exc).__name__,
                                            max_attempts=max_attempts)
                    failure = failure or exc
                    continue
                if not provider:
                    self.journal.record(
                        "extract",
                        "warning",
                        "provider is not configured; keeping pending input",
                        stage="provider.resolve",
                        context={"session": session_id, "topic": topic_id},
                    )
                    continue
                ready.append((session_id, topic_id, part, provider))
            if not ready:
                if failure is not None:
                    raise failure
                return 0, 0
            self.flush_count += 1
            written = 0
            for session_id, topic_id, part, provider in ready:
                for chunk in chunk_turns(part):
                    try:
                        with self.journal.span(
                            "extract",
                            "topic.extract",
                            session=session_id,
                            topic=topic_id,
                            messages=len(chunk),
                        ) as metrics:
                            outcome = await absorb(
                                chunk,
                                self.artifacts,
                                self.sources,
                                self.cache,
                                self.graph,
                                ProviderChatModel(provider),
                                log=partial(self.journal.record, "extract", "warning"),
                                owner_id=self.owner_id(),
                                strict=True,
                                stage=partial(self.journal.span, "extract"),
                            )
                            metrics["written"] = outcome.written
                            metrics["skipped"] = outcome.skipped
                            if outcome.model_failed or outcome.retryable:
                                raise RuntimeError(
                                    "extraction failed; keep pending input"
                                )
                    except Exception as exc:
                        self.buffer.mark_failed(
                            chunk,
                            type(exc).__name__,
                            max_attempts=max_attempts,
                        )
                        failure = failure or exc
                        break
                    self.buffer.mark_succeeded(chunk)
                    written += outcome.written
                    self.logger.info(
                        f"[seekmemory] {reason} extract "
                        f"{session_id or 'unknown'}: topic {topic_id}, "
                        f"{len(chunk)} turns, {outcome.written} written"
                    )
            self.journal.record(
                "extract",
                "info",
                f"tried {len(ready)} topics, wrote {written} memories",
                context={"topics": len(ready), "written": written},
                stage="batch.complete",
            )
            if failure is not None:
                raise failure
            return written, len(ready)
        finally:
            self.flushing = False
