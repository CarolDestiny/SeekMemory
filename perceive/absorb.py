"""把缓冲里的对话抽成记忆并落库。

一步做完：拼对话 → 调模型 → 解析 JSON → 去重 → 构造 artifact → 校验 → 写库建边。
任何一步失败都只丢这一批，不影响聊天。
"""

from __future__ import annotations

import datetime
import re
from typing import Any, Callable

try:  # 作为 astrbot 插件包的一部分导入
    from ..core.artifact import Lineage, Strength, TimeSpan, content_of, make, validate
    from ..core.graph import Graph
    from ..maintain.impression import revise_impression
    from ..maintain.link import link_new
    from ..perceive.extract import (
        build_prompt,
        filter_duplicates,
        parse_response,
    )
    from ..store.cache import Cache
    from ..store.db import DB
    from ..app.contracts import ChatRequest, DialogueTurn, WriteOutcome
except ImportError:  # 作为顶层包导入（脚本 / 测试）
    from core.artifact import Lineage, Strength, TimeSpan, content_of, make, validate
    from core.graph import Graph
    from maintain.impression import revise_impression
    from maintain.link import link_new
    from perceive.extract import build_prompt, filter_duplicates, parse_response
    from store.cache import Cache
    from store.db import DB
    from app.contracts import ChatRequest, DialogueTurn, WriteOutcome

MAX_ITEMS = 6

# 值得不等晚上的信号：计划与日期、稳定事实、强情绪。命中任一就当场抽。
_PLAN = re.compile(r"(下周|明天|后天|下个月|周末|计划|打算|准备|约了|要去|出差|搬家|"
                   r"面试|入职|离职|辞职|生日|纪念日|考试|体检)")
_FACT = re.compile(r"(我叫|名字|住在|老家|公司|工作|职业|女朋友|男朋友|老婆|老公|对象|"
                   r"爸|妈|猫|狗|住院|手术|升职|加薪|毕业)")
_STRONG = re.compile(r"(崩溃|吵架|分手|哭了|想死|撑不住|很难受|被骂|裁员|辞退|生病|发烧)")
_NOT_WORTH = re.compile(r"^(早|晚安|在吗|在不在|哈哈|嗯|哦|好|好的|收到)[。！？!?~～]*$")
Log = Callable[[str], None]


def _parse_time(value: Any) -> datetime.datetime | None:
    try:
        return datetime.datetime.fromisoformat(str(value or "").strip())
    except (TypeError, ValueError):
        try:
            return datetime.datetime.fromisoformat(str(value or "").strip() + "T00:00:00")
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
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    if number != number:  # NaN
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


def dialogue_of(items: list[DialogueTurn]) -> str:
    lines = []
    for turn in items[-120:]:
        who = f"{turn.role}({turn.speaker_id})" if turn.speaker_id else turn.role
        prefix = f"[{turn.at}] " if turn.at else ""
        lines.append(f"{prefix}{who}: {turn.text}")
    return "\n".join(lines)


def existing_texts(cache: Cache | None) -> list[str]:
    """已有记忆正文，供抽取去重。"""
    if cache is None:
        return []
    try:
        return [content_of(a) for a in cache.active("memory")]
    except Exception:  # noqa: BLE001 - 读不到就当作没有
        return []


def owner_of(items: list[DialogueTurn]) -> str:
    sessions = {turn.session_id for turn in items if turn.session_id}
    return next(iter(sessions)) if len(sessions) == 1 else ""


async def absorb(
    items: list[DialogueTurn],
    db: DB,
    cache: Cache | None,
    graph: Graph | None,
    model: Any,
    log: Log = lambda _msg: None,
    owner_id: str = "",
) -> WriteOutcome:
    if not items or db is None or model is None:
        return WriteOutcome(errors=("invalid extraction input",))
    try:
        if hasattr(model, "complete"):
            resp = await model.complete(ChatRequest(session_id=str(items[0].session_id or ""),
                                                    system_prompt=build_prompt([]),
                                                    prompt=dialogue_of(items)))
            raw = getattr(resp, "text", "") or ""
        else:
            resp = await model.text_chat(system_prompt=build_prompt([]), prompt=dialogue_of(items))
            raw = getattr(resp, "completion_text", "") or ""
    except Exception as exc:
        log(f"model extraction failed: {exc}")
        return WriteOutcome(errors=(f"model: {exc}",), model_failed=True)

    parsed = parse_response(raw)
    parsed = filter_duplicates(parsed, existing_texts(cache))
    if not parsed:
        return WriteOutcome(skipped=len(items))

    owner = owner_of(items)
    source_ids = tuple(turn.source_id for turn in items if turn.source_id)
    group = ":GroupMessage:" in owner
    senders = {turn.speaker_id for turn in items if turn.speaker_id}
    said_by = "owner"
    if group:
        said_by = next(iter(senders)) if len(senders) == 1 else "group"
    default_subject = next(iter(senders), owner or "")
    written_ids: list[str] = []
    skipped = 0
    errors: list[str] = []
    for item in parsed[:MAX_ITEMS]:
        try:
            if owner:
                item = {**item, "owner_umo": owner}
            payload = dict(item)
            if group and len(senders) > 1:
                payload["speakers"] = sorted(senders)
            strength = strength_of(item)
            if not source_ids:
                payload["legacy_no_source"] = True
                strength["confidence"] = min(float(strength.get("confidence", 1.0)), 0.5)
            event_at = _event_at(item, items)
            art = make("memory", payload, strength=strength,
                       scope="shared" if group or not owner else "private",
                       said_by=said_by,
                       subject_id=_subject_id(item, owner, default_subject, owner_id),
                       lineage=Lineage(sources=source_ids),
                       time=TimeSpan(created=event_at,
                                     valid_from=_date_or_none(item.get("valid_from")),
                                     valid_to=_date_or_none(item.get("valid_to"))))
            validate(art)
        except Exception as exc:
            skipped += 1
            errors.append(f"construct: {exc}")
            log(f"artifact construct failed: {exc}")
            continue
        try:
            db.commit(art, expected_revision=0, op="create", reason="extract",
                      source_ids=source_ids)
            if cache is not None:
                cache.put(art)
            link_new(art, graph, cache)
            written_ids.append(art.header.id)
        except Exception as exc:
            skipped += 1
            errors.append(f"commit: {exc}")
            log(f"artifact commit failed: {exc}")
            continue
        try:
            if cache is not None and str(payload.get("level") or "") == "impression":
                revise_impression(db, cache, art)
        except Exception as exc:
            errors.append(f"impression: {exc}")
            log(f"impression revision failed: {exc}")
    return WriteOutcome(written=len(written_ids), skipped=skipped,
                        ids=tuple(written_ids), errors=tuple(errors))
