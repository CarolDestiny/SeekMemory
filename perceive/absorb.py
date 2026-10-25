"""Turn pending dialogue into validated Artifacts without persistence.

The IngestService owns model calls and every write side effect.
"""

from __future__ import annotations

import datetime
import math
import re
from dataclasses import dataclass
from contextlib import AbstractContextManager, nullcontext
from collections.abc import Callable
from typing import Any

try:  # 作为 astrbot 插件包的一部分导入
    from ..app.contracts import DialogueTurn, WriteOutcome
    from ..core.artifact import Artifact, Lineage, Strength, TimeSpan, content_of, make, validate
    from ..perceive.behavior import (
        DEFAULT_BEHAVIOR_CONFIDENCE,
        behavior_boundary,
        behavior_of,
        check_payload,
        dedupe_behaviors,
        evidence_ids,
        is_behavior,
        is_behavior_key,
        payload_of,
        validate_evidence,
    )
    from ..perceive.extract import (
        ExtractionParseError,
        filter_duplicates,
        parse_response_checked,
    )
    from ..app.ports import ArtifactCache, SourceStore
except ImportError:  # 作为顶层包导入（脚本 / 测试）
    from app.contracts import DialogueTurn, WriteOutcome
    from core.artifact import Artifact, Lineage, Strength, TimeSpan, content_of, make, validate
    from app.ports import ArtifactCache, SourceStore

    from perceive.behavior import (
        DEFAULT_BEHAVIOR_CONFIDENCE,
        behavior_boundary,
        behavior_of,
        check_payload,
        dedupe_behaviors,
        evidence_ids,
        is_behavior,
        is_behavior_key,
        payload_of,
        validate_evidence,
    )
    from perceive.extract import (
        ExtractionParseError,
        filter_duplicates,
        parse_response_checked,
    )

MAX_ITEMS = 6

# 值得不等晚上的信号：计划与日期、稳定事实、强情绪。命中任一就当场抽。
_PLAN = re.compile(
    r"(下周|明天|后天|下个月|周末|计划|打算|准备|约了|要去|出差|搬家|"
    r"面试|入职|离职|辞职|生日|纪念日|考试|体检)"
)
_FACT = re.compile(
    r"(我叫|名字|住在|老家|公司|工作|职业|女朋友|男朋友|老婆|老公|对象|"
    r"爸|妈|猫|狗|住院|手术|升职|加薪|毕业)"
)
_STRONG = re.compile(
    r"(崩溃|吵架|分手|哭了|想死|撑不住|很难受|被骂|裁员|辞退|生病|发烧)"
)
_NOT_WORTH = re.compile(
    r"^(早|晚安|在吗|在不在|哈哈|嗯|哦|好|好的|收到)[。！？!?~～]*$"
)
Log = Callable[[str], None]


def _parse_time(value: Any) -> datetime.datetime | None:
    try:
        return datetime.datetime.fromisoformat(str(value or "").strip())
    except (TypeError, ValueError):
        try:
            return datetime.datetime.fromisoformat(
                str(value or "").strip() + "T00:00:00"
            )
        except (TypeError, ValueError):
            return None


def _date_or_none(value: Any) -> str | None:
    parsed = _parse_time(value)
    return parsed.date().isoformat() if parsed is not None else None


def _event_at(item: dict, turns: list[DialogueTurn]) -> str:
    parsed = _parse_time(item.get("event_at"))
    if parsed is not None:
        return parsed.isoformat(timespec="seconds")
    wanted = item.get("event_date") or item.get("valid_from")
    parsed = _parse_time(wanted)
    if parsed is not None:
        return parsed.isoformat(timespec="seconds")
    stamps = [_parse_time(turn.at) for turn in turns]
    valid = [stamp for stamp in stamps if stamp is not None]
    if valid:
        return min(valid).isoformat(timespec="seconds")
    return datetime.datetime.now().isoformat(timespec="seconds")


def _subject_id(item: dict, owner: str, default: str, owner_id: str = "") -> str:
    kind = str(item.get("subject_kind") or "").strip()
    raw = str(item.get("subject_id") or "").strip()
    if raw and raw not in ("owner", "speaker", "self", "world", "relation"):
        return raw
    if not owner_id and owner:
        owner_id = str(owner).split(":")[-1]
    if kind == "owner":
        return owner_id or default
    if kind == "speaker":
        return default
    if kind in ("world", "relation", "self"):
        return kind
    name = str(item.get("subject_name") or "").strip()
    return "third:" + name if name else default


def _num(value: Any, default: float, low: float, high: float) -> float:
    """把模型给的数值收进区间；缺失、NaN 或非法值回落到默认值。"""
    if isinstance(value, bool):
        return default
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return max(low, min(high, number))


def strength_of(item: dict) -> dict:
    """从抽取结果取情绪与命中字段，缺省回落到 Strength 的默认值。"""
    base = Strength()
    out = {
        "arousal": _num(item.get("arousal"), base.arousal, 0.0, 1.0),
        "valence": _num(item.get("valence"), base.valence, -1.0, 1.0),
        "funny": _num(item.get("funny"), base.funny, 0.0, 1.0),
    }
    if "confidence" in item or is_behavior(item):
        # 行为条目没给 confidence 时保守落在 0.9 以下；老式普通事实保持兼容默认。
        default = DEFAULT_BEHAVIOR_CONFIDENCE if is_behavior(item) else base.confidence
        out["confidence"] = _num(item.get("confidence"), default, 0.0, 1.0)
    hits = item.get("hits")
    if hits is not None:
        try:
            out["hits"] = max(0, int(hits))
        except (TypeError, ValueError):
            pass
    return out


def worth_now(items: list[DialogueTurn]) -> bool:
    for turn in items[-30:]:
        if turn.role != "user":
            continue
        line = str(turn.text or "").strip()
        if not line or _NOT_WORTH.match(line):
            continue
        if _PLAN.search(line) or _FACT.search(line) or _STRONG.search(line):
            return True
    return False


def _dialog_rows(items: list[DialogueTurn]) -> list[DialogueTurn]:
    """Return every supplied row; the caller owns bounded chunks.

    ``_flush`` already chunks the original rows, and a recovered immutable
    parent can push the pairing context above the chunk size. Rendering that
    context in full is safe, so no supplied row may be silently lost.
    """
    return list(items)


def dialogue_of(
    items: list[DialogueTurn], *, include_topic: bool = False
) -> str:
    """Render lines with explicit source labels so evidence ids can be cited.

    Topic labels are opt-in for multi-topic batches; the default rendering is
    unchanged for existing extraction and tests.
    """
    lines = []
    for turn in _dialog_rows(items):
        who = f"{turn.role}({turn.speaker_id})" if turn.speaker_id else turn.role
        if turn.source_id:
            who = f"{who}[{turn.source_id}]"
        if turn.role == "assistant" and turn.reply_to:
            who += f" reply_to={turn.reply_to}"
        prefix = f"[{turn.at}] " if turn.at else ""
        topic = f"topic={turn.topic_id} " if include_topic and turn.topic_id else ""
        lines.append(f"{prefix}{topic}{who}: {turn.text}")
    return "\n".join(lines)


def recover_parents(items: list[DialogueTurn], sources: SourceStore | None) -> list[DialogueTurn]:
    """Recover already-extracted user parents as read-only pairing context.

    A chunk boundary or a restart can leave an assistant turn without the user
    turn it replies to. The immutable Source is read back only for pairing and
    evidence: it is never re-queued, re-marked succeeded or re-written.

    Raises:
        Exception: When the Source lookup fails, so the caller can keep the
            pending rows retryable instead of extracting without context.
    """
    rows = list(items)
    if sources is None:
        return rows
    present = {turn.source_id for turn in items if turn.source_id}
    wanted: list[str] = []
    for turn in items:
        parent_id = str(turn.reply_to or "")
        if turn.role != "assistant" or not parent_id or parent_id in present:
            continue
        if parent_id not in wanted:
            wanted.append(parent_id)
    if not wanted:
        return rows
    source_rows = sources.sources_by_ids(wanted)
    out: list[DialogueTurn] = []
    added: set[str] = set()
    for turn in items:
        parent_id = str(turn.reply_to or "") if turn.role == "assistant" else ""
        parent = source_rows.get(parent_id) if parent_id else None
        # 只有同会话、role=user、且就是被回复的那条 Source 才能进提示词。
        if parent is not None and parent.id not in present and parent.id not in added:
            same_session = parent.session_id == turn.session_id
            if parent.role == "user" and same_session and parent.id == parent_id:
                added.add(parent.id)
                out.append(
                    DialogueTurn(
                        parent.session_id,
                        parent.speaker_id,
                        parent.role,
                        parent.text,
                        parent.at,
                        parent.id,
                        "",
                        parent.turn_id,
                        parent.reply_to,
                    )
                )
        out.append(turn)
    return out


def existing_texts(cache: ArtifactCache | None) -> list[str]:
    """已有记忆正文，供抽取去重。"""
    if cache is None:
        return []
    try:
        return [content_of(a) for a in cache.active("memory")]
    except Exception:  # noqa: BLE001 - 读不到就当作没有
        return []


def _boundary(scope: str, subject_id: str) -> str:
    return f"{scope}\x1f{subject_id}"


def existing_texts_by_subject(cache: ArtifactCache | None) -> dict[str, list[str]]:
    """Existing memory text grouped by subject, scope and behavior evidence.

    Ordinary memories keep the plain subject boundary. Behavior memories are
    keyed by their own evidence so a new episode with the same wording but
    different assistant evidence is not mistaken for a repeat.
    """
    if cache is None:
        return {}
    out: dict[str, list[str]] = {}
    try:
        for art in cache.active("memory"):
            boundary = _boundary(str(art.header.scope or "private"),
                                 str(art.header.subject_id or ""))
            if is_behavior(art.payload):
                boundary = behavior_boundary(
                    boundary,
                    behavior_of(art.payload),
                    art.header.lineage.sources,
                )
            out.setdefault(boundary, []).append(content_of(art))
    except Exception:  # noqa: BLE001 - a broken cache view means no dedupe history
        return {}
    return out


def owner_of(items: list[DialogueTurn]) -> str:
    sessions = {turn.session_id for turn in items if turn.session_id}
    return next(iter(sessions)) if len(sessions) == 1 else ""


@dataclass(frozen=True)
class ExtractionPlan:
    """Pure extraction result ready for the ingest service to persist."""
    artifacts: tuple[Artifact, ...] = ()
    skipped: int = 0
    errors: tuple[str, ...] = ()
    retryable: bool = False
    outcome: WriteOutcome | None = None


def build_plan(
    items: list[DialogueTurn],
    context: list[DialogueTurn],
    raw: str,
    cache: ArtifactCache | None,
    owner_id: str = "",
    log: Log = lambda _msg: None,
    *,
    strict: bool = False,
    stage: Callable[[str], AbstractContextManager[object]] = lambda _name: (
        nullcontext()
    ),
) -> ExtractionPlan:
    """Convert model output into validated Artifacts without side effects.

    The function reads the cache for dedupe only. It never commits, caches,
    links, supersedes or revises anything; those writes belong to IngestService.
    """
    owner = owner_of(items)
    available = {turn.source_id: turn for turn in context if turn.source_id}
    source_ids = tuple(turn.source_id for turn in items if turn.source_id)
    group = ":GroupMessage:" in owner
    scope = "shared" if group or not owner else "private"
    senders = {turn.speaker_id for turn in items if turn.speaker_id}
    user_senders = {
        turn.speaker_id for turn in context
        if turn.speaker_id and turn.role == "user"
    }
    said_by = "owner"
    if group:
        said_by = next(iter(user_senders)) if len(user_senders) == 1 else "group"
    default_subject = (
        next(iter(user_senders)) if len(user_senders) == 1
        else owner_id or owner or ""
    )

    def boundary_of(item: dict) -> str:
        base = _boundary(scope, _subject_id(item, owner, default_subject, owner_id))
        if not is_behavior(item):
            return base
        return behavior_boundary(base, behavior_of(item), evidence_ids(item))

    try:
        with stage("response.parse"):
            parsed = parse_response_checked(raw)
    except ExtractionParseError as exc:
        if strict:
            raise
        return ExtractionPlan(outcome=WriteOutcome(
            errors=(f"parse: {exc}",), model_failed=True, retryable=True
        ))

    checked: list[tuple[dict, tuple[str, ...]]] = []
    for item in parsed[:MAX_ITEMS]:
        candidate = {**item, "owner_umo": owner} if owner else dict(item)
        try:
            check_payload(candidate)
            evidence = validate_evidence(candidate, available, session_id=owner)
        except ValueError as exc:
            log(f"evidence validation failed: {type(exc).__name__}")
            return ExtractionPlan(outcome=WriteOutcome(
                errors=(f"evidence: {exc}",), model_failed=True, retryable=True
            ))
        checked.append((candidate, evidence))
    evidence_of = {id(item): evidence for item, evidence in checked}
    parsed = [item for item, _ in checked]

    with stage("memory.deduplicate"):
        existing = existing_texts_by_subject(cache)
        repeated = {key for key in existing if is_behavior_key(key)}
        parsed = dedupe_behaviors(
            parsed, existing_keys=repeated, boundary_of=boundary_of
        )
        parsed = filter_duplicates(
            parsed,
            existing_by_subject=existing,
            subject_of=boundary_of,
        )
    if not parsed:
        return ExtractionPlan(outcome=WriteOutcome(skipped=len(items)))

    artifacts: list[Artifact] = []
    skipped = 0
    errors: list[str] = []
    retryable = False
    for item in parsed:
        evidence = evidence_of.get(id(item), ())
        try:
            payload = payload_of(item)
            if group and len(senders) > 1:
                payload["speakers"] = sorted(senders)
            strength = strength_of(item)
            if not source_ids:
                payload["legacy_no_source"] = True
                strength["confidence"] = min(
                    float(strength.get("confidence", 1.0)), 0.5
                )
            with stage("artifact.validate"):
                art = make(
                    "memory",
                    payload,
                    strength=strength,
                    scope=scope,
                    said_by=said_by,
                    subject_id=_subject_id(item, owner, default_subject, owner_id),
                    lineage=Lineage(sources=evidence or source_ids),
                    time=TimeSpan(
                        created=_event_at(item, context),
                        valid_from=_date_or_none(item.get("valid_from")),
                        valid_to=_date_or_none(item.get("valid_to")),
                    ),
                )
                validate(art)
            artifacts.append(art)
        except Exception as exc:
            skipped += 1
            retryable = True
            errors.append(f"construct: {exc}")
            log(f"artifact validation failed: {type(exc).__name__}")
    return ExtractionPlan(tuple(artifacts), skipped, tuple(errors), retryable)
