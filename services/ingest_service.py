"""Pending-buffer extraction service."""

from __future__ import annotations

import datetime
import re
from dataclasses import replace
from functools import partial
from contextlib import AbstractContextManager, nullcontext
from typing import Any, Awaitable, Callable

try:
    from ..app.contracts import ChatRequest, DialogueTurn, WriteOutcome
    from ..app.flush_policy import chunk_turns, decide_flush, select_topic_batches
    from ..app.ports import ArtifactStore, ExtractionStore, SourceStore
    from ..core.artifact import content_of, revise
    from ..core.capacity import PROTECTIVE, SATURATED
    from ..maintain.impression import revise_impression
    from ..maintain.link import link_new
    from ..perceive.absorb import ExtractionPlan, build_plan, dialogue_of, recover_parents, worth_now
    from ..perceive.extract import build_prompt
    from ..perceive.importance import (
        MIN_IMPORTANCE_SCORE,
        TopicImportance,
        rank_topics,
        select_important_topics,
        select_ranked_topics,
    )
    from ..perceive.model import ProviderChatModel
except ImportError:
    from app.contracts import ChatRequest, DialogueTurn, WriteOutcome
    from app.flush_policy import chunk_turns, decide_flush, select_topic_batches
    from app.ports import ArtifactStore, ExtractionStore, SourceStore
    from core.artifact import content_of, revise
    from core.capacity import PROTECTIVE, SATURATED
    from maintain.impression import revise_impression
    from maintain.link import link_new
    from perceive.absorb import ExtractionPlan, build_plan, dialogue_of, recover_parents, worth_now
    from perceive.extract import build_prompt
    from perceive.importance import (
        MIN_IMPORTANCE_SCORE,
        TopicImportance,
        rank_topics,
        select_important_topics,
        select_ranked_topics,
    )
    from perceive.model import ProviderChatModel


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
        self._usage_calls = 0
        self._usage_in = 0
        self._usage_cached = 0
        self._usage_out = 0

    def usage_snapshot(self) -> dict[str, int]:
        """Return cumulative content-free extraction usage counters."""
        return {
            "calls": int(self._usage_calls),
            "in": int(self._usage_in),
            "cached": int(self._usage_cached),
            "out": int(self._usage_out),
        }

    @staticmethod
    def _response_usage(response: Any) -> tuple[int, int, int]:
        def number(value: Any) -> int:
            try:
                return max(0, int(value or 0))
            except (TypeError, ValueError):
                return 0

        usage = getattr(response, "usage", None)
        if usage is None:
            return (
                number(getattr(response, "usage_in", 0)),
                number(getattr(response, "usage_cached", 0)),
                number(getattr(response, "usage_out", 0)),
            )
        return (
            number(getattr(usage, "input", 0)),
            number(getattr(usage, "input_cached", 0)),
            number(getattr(usage, "output", 0)),
        )

    def _record_usage(self, usage: tuple[int, int, int]) -> None:
        self._usage_calls += 1
        self._usage_in += max(0, int(usage[0]))
        self._usage_cached += max(0, int(usage[1]))
        self._usage_out += max(0, int(usage[2]))

    @staticmethod
    def _with_usage(outcome: WriteOutcome, usage: tuple[int, int, int]) -> WriteOutcome:
        return replace(
            outcome,
            usage_in=max(0, int(usage[0])),
            usage_cached=max(0, int(usage[1])),
            usage_out=max(0, int(usage[2])),
        )

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

    def split_topics(
        self,
        items: list[DialogueTurn],
        cap: int | None = None,
        triage: bool = False,
        ranked: list[TopicImportance] | None = None,
    ) -> list[tuple[str, str, list[DialogueTurn]]]:
        limit = int(cap or self.config("max_sessions_per_flush", 6))
        if triage:
            if ranked is None:
                return select_important_topics(items, limit)
            return select_ranked_topics(ranked, limit)
        return select_topic_batches(items, limit)

    async def flush(
        self,
        reason: str,
        *,
        limit: int = 0,
        batch_cap: int = 6,
        max_attempts: int = 5,
        max_calls: int = 0,
        max_tokens: int = 0,
        triage: bool = False,
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
            pending = list(self.buffer.items)
            ranked = rank_topics(pending) if triage else None
            topics = self.split_topics(
                pending,
                cap=limit or batch_cap,
                triage=triage,
                ranked=ranked,
            )
            triage_metrics: dict[str, int] = {}
            if triage:
                eligible = sum(
                    1 for item in ranked
                    if item.score >= MIN_IMPORTANCE_SCORE
                )
                triage_metrics = {
                    "candidates": len(ranked),
                    "eligible": eligible,
                    "selected": len(topics),
                    "skipped_low_value": len(ranked) - eligible,
                }
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
                if triage_metrics:
                    self.journal.record(
                        "extract",
                        "info",
                        "triage selected no extractable topics",
                        context=triage_metrics,
                        stage="triage",
                    )
                return 0, 0
            self.flush_count += 1
            usage_base = self.usage_snapshot()
            written = 0
            calls = 0
            processed_topics = 0
            stopped_for_budget = False

            def token_budget_exhausted() -> bool:
                if max_tokens <= 0:
                    return False
                current = self.usage_snapshot()
                used = max(
                    0,
                    current["in"] + current["out"]
                    - usage_base["in"] - usage_base["out"],
                )
                return used >= max_tokens

            for session_id, topic_id, part, provider in ready:
                topic_started = False
                for chunk in chunk_turns(part):
                    if (
                        (max_calls > 0 and calls >= max_calls)
                        or token_budget_exhausted()
                    ):
                        stopped_for_budget = True
                        break
                    topic_started = True
                    calls += 1
                    try:
                        with self.journal.span(
                            "extract",
                            "topic.extract",
                            session=session_id,
                            topic=topic_id,
                            messages=len(chunk),
                        ) as metrics:
                            outcome = await self.extract(
                                chunk,
                                ProviderChatModel(provider),
                                log=partial(self.journal.record, "extract", "warning"),
                                strict=True,
                                stage=partial(self.journal.span, "extract"),
                            )
                            metrics["written"] = outcome.written
                            metrics["skipped"] = outcome.skipped
                            metrics["usage_in"] = outcome.usage_in
                            metrics["usage_cached"] = outcome.usage_cached
                            metrics["usage_out"] = outcome.usage_out
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
                if topic_started:
                    processed_topics += 1
                if stopped_for_budget:
                    break
            context = {"topics": processed_topics, "written": written}
            context.update(triage_metrics)
            self.journal.record(
                "extract",
                "info",
                f"tried {processed_topics} topics, wrote {written} memories",
                context=context,
                stage="batch.complete",
            )
            if failure is not None:
                raise failure
            return written, processed_topics
        finally:
            self.flushing = False

    async def extract(
        self,
        items,
        model,
        *,
        owner_id: str | None = None,
        log: Callable[[str], None] = lambda _msg: None,
        strict: bool = False,
        stage: Callable[[str], AbstractContextManager[object]] = lambda _name: (
            nullcontext()
        ),
    ) -> WriteOutcome:
        """Call the model, build a pure plan, then persist through this service."""
        if (
            not items
            or self.artifacts is None
            or self.sources is None
            or model is None
        ):
            return WriteOutcome(errors=("invalid extraction input",))
        items = list(items)
        owner = self.owner_id() if owner_id is None else owner_id
        try:
            context = recover_parents(items, self.sources)
        except Exception as exc:
            if strict:
                raise
            log(f"parent recovery failed: {type(exc).__name__}")
            return WriteOutcome(errors=(f"parent: {exc}",), retryable=True)

        try:
            with stage("provider.call"):
                if hasattr(model, "complete"):
                    response = await model.complete(
                        ChatRequest(
                            session_id=str(items[0].session_id or ""),
                            system_prompt=build_prompt([]),
                            prompt=dialogue_of(context),
                        )
                    )
                    raw = getattr(response, "text", "") or ""
                else:
                    response = await model.text_chat(
                        system_prompt=build_prompt([]),
                        prompt=dialogue_of(context),
                    )
                    raw = getattr(response, "completion_text", "") or ""
            usage = self._response_usage(response)
            self._record_usage(usage)
        except Exception as exc:
            if strict:
                raise
            log(f"model call failed: {type(exc).__name__}")
            return WriteOutcome(
                errors=(f"model: {exc}",), model_failed=True, retryable=True
            )

        plan = build_plan(
            items, context, raw, self.cache, owner, log, strict=strict, stage=stage
        )
        if plan.outcome is not None:
            return self._with_usage(plan.outcome, usage)
        return self._persist_plan(plan, stage, log, usage=usage)

    def _persist_plan(
        self,
        plan: ExtractionPlan,
        stage: Callable[[str], AbstractContextManager[object]],
        log: Callable[[str], None],
        *,
        usage: tuple[int, int, int] = (0, 0, 0),
    ) -> WriteOutcome:
        written_ids: list[str] = []
        skipped = plan.skipped
        errors = list(plan.errors)
        retryable = plan.retryable
        for art in plan.artifacts:
            try:
                with stage("artifact.persist"):
                    self.artifacts.commit(
                        art,
                        expected_revision=0,
                        op="create",
                        reason="extract",
                        source_ids=tuple(art.header.lineage.sources),
                    )
                    if self.cache is not None:
                        self.cache.put(art)
                    link_new(art, self.graph, self.cache)
                    written_ids.append(art.header.id)
                    try:
                        self._supersede(art)
                    except Exception as exc:
                        errors.append(f"supersede: {exc}")
            except Exception as exc:
                skipped += 1
                errors.append(f"commit: {exc}")
                retryable = True
                log(f"memory write failed: {type(exc).__name__}")
                continue
            try:
                if (
                    self.cache is not None
                    and str(art.payload.get("level") or "") == "impression"
                ):
                    with stage("impression.revise"):
                        revise_impression(self.artifacts, self.cache, art)
            except Exception as exc:
                errors.append(f"impression: {exc}")
                log(f"impression revision failed: {type(exc).__name__}")
        return self._with_usage(
            WriteOutcome(
                written=len(written_ids),
                skipped=skipped,
                ids=tuple(written_ids),
                errors=tuple(errors),
                retryable=retryable,
            ),
            usage,
        )

    def _supersede(self, new_art) -> int:
        """Expire an explicitly superseded old memory without deleting its Source."""
        payload = new_art.payload if isinstance(new_art.payload, dict) else {}
        old_text = str(payload.get("supersedes") or "").strip()
        if not old_text or self.cache is None:
            return 0
        key = re.sub(r"\s+", "", old_text).lower()
        cutoff = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        changed = 0
        for old in list(self.cache.active("memory")):
            if old.header.id == new_art.header.id:
                continue
            if old.header.subject_id != new_art.header.subject_id:
                continue
            if old.header.scope != new_art.header.scope:
                continue
            body = re.sub(r"\s+", "", content_of(old) or "").lower()
            if not key or not body or (key not in body and body not in key):
                continue
            updated = revise(old, time=replace(old.header.time, valid_to=cutoff))
            self.artifacts.commit(
                updated,
                expected_revision=old.header.revision,
                op="revise",
                reason="superseded by extraction",
                source_ids=tuple(old.header.lineage.sources),
            )
            self.cache.put(updated)
            changed += 1
        return changed
