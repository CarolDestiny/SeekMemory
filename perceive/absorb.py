"""把缓冲里的对话抽成记忆并落库。

一步做完：拼对话 → 调模型 → 解析 JSON → 去重 → 构造 artifact → 校验 → 写库建边。
任何一步失败都只丢这一批，不影响聊天。
"""

from __future__ import annotations

import re
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from typing import Any

try:  # 作为 astrbot 插件包的一部分导入
    from ..app.contracts import ChatRequest
    from ..core.artifact import Lineage, Strength, content_of, make, validate
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
except ImportError:  # 作为顶层包导入（脚本 / 测试）
    from app.contracts import ChatRequest
    from core.artifact import Lineage, Strength, content_of, make, validate
    from core.graph import Graph
    from maintain.impression import revise_impression
    from maintain.link import link_new
    from store.cache import Cache
    from store.db import DB

    from perceive.extract import build_prompt, filter_duplicates, parse_response

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


def _parts(row: tuple) -> tuple[str, str, str, str]:
    return (
        str(row[0]),
        str(row[1]) if len(row) > 1 else "",
        str(row[2]) if len(row) > 2 else "",
        str(row[3]) if len(row) > 3 else "",
    )


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


def worth_now(items: list[tuple]) -> bool:
    """这批对话里有没有值得当场记住的事（计划/事实/强情绪）。"""
    for row in items[-30:]:
        _umo, _sender, role, text = _parts(row)
        if str(role) != "user":
            continue
        line = str(text or "").strip()
        if not line or _NOT_WORTH.match(line):
            continue
        if _PLAN.search(line) or _FACT.search(line) or _STRONG.search(line):
            return True
    return False


def dialogue_of(items: list[tuple]) -> str:
    """把 (umo, sender, role, text) 拼成给模型看的对话文本；群里带是谁说的。"""
    lines = []
    for row in items[-120:]:
        _umo, sender, role, text = _parts(row)
        who = f"{role}({sender})" if sender else role
        lines.append(f"{who}: {text}")
    return "\n".join(lines)


def existing_texts(cache: Cache | None) -> list[str]:
    """已有记忆正文，供抽取去重。"""
    if cache is None:
        return []
    try:
        return [content_of(a) for a in cache.active("memory")]
    except Exception:  # noqa: BLE001 - 读不到就当作没有
        return []


def owner_of(items: list[tuple]) -> str:
    """只有整批来自同一个会话时才记归属，混会话就不写归属。"""
    umos = {item[0] for item in items if item[0]}
    return next(iter(umos)) if len(umos) == 1 else ""


async def absorb(
    items: list[tuple],
    db: DB,
    cache: Cache | None,
    graph: Graph | None,
    model: Any,
    log: Log = lambda _msg: None,
    *,
    strict: bool = False,
    stage: Callable[[str], AbstractContextManager[object]] = lambda _name: (
        nullcontext()
    ),
) -> int:
    """抽取并持久化 Artifact，对单条处理失败保持容错。

    Args:
        items: 缓冲中的对话记录。
        db: 运行中的 Artifact 数据库。
        cache: 可选的运行中 Artifact 缓存。
        graph: 可选的关系图，用于关联新 Artifact。
        model: 上游 ChatModel 接口或兼容的模型服务。
        log: 操作警告回调。
        strict: 传播模型服务异常，使任务执行器保留待处理输入。
        stage: 注入的业务阶段上下文管理器；默认不采集阶段日志。

    Returns:
        持久化的 Artifact 数量；输出为空或全部被拒绝时返回零。

    Raises:
        Exception: 启用 strict 时传播的模型服务异常。
    """
    if not items or db is None or model is None:
        return 0
    try:
        with stage("provider.call"):
            if hasattr(model, "complete"):
                resp = await model.complete(
                    ChatRequest(
                        session_id=str(items[0][0] or ""),
                        system_prompt=build_prompt([]),
                        prompt=dialogue_of(items),
                    )
                )
                raw = getattr(resp, "text", "") or ""
            else:
                resp = await model.text_chat(
                    system_prompt=build_prompt([]), prompt=dialogue_of(items)
                )
                raw = getattr(resp, "completion_text", "") or ""
    except Exception as exc:  # noqa: BLE001 - 抽取失败不抛给上层
        if strict:
            raise
        log(f"模型调用失败： {type(exc).__name__}")
        return 0

    with stage("response.parse"):
        parsed = parse_response(raw)
    with stage("memory.deduplicate"):
        parsed = filter_duplicates(parsed, existing_texts(cache))
    if not parsed:
        return 0

    owner = owner_of(items)
    source_ids = tuple(str(row[4]) for row in items if len(row) > 4 and row[4])
    group = ":GroupMessage:" in owner
    senders = {item[1] for item in items if item[1]}
    said_by = "owner"
    if group:
        said_by = next(iter(senders)) if len(senders) == 1 else "group"
    default_subject = next(iter(senders), owner or "")
    written = 0
    for item in parsed[:MAX_ITEMS]:
        try:
            if owner:
                item = {**item, "owner_umo": owner}
            # 按人归属：群聊不是隐私边界，群里发生的写 shared；
            # 私聊写 private，只归那个会话。说话人记录在 said_by / speakers。
            payload = item
            if group and len(senders) > 1:
                payload = {**item, "speakers": sorted(senders)}
            with stage("artifact.validate"):
                art = make(
                    "memory",
                    payload,
                    strength=strength_of(item),
                    scope="shared" if group or not owner else "private",
                    said_by=said_by,
                    subject_id=str(item.get("subject_id") or default_subject),
                    lineage=Lineage(sources=source_ids),
                )
                validate(art)
        except Exception as exc:  # noqa: BLE001 - 单条坏数据跳过
            log(f"记忆校验失败： {type(exc).__name__}")
            continue
        try:
            with stage("artifact.persist"):
                db.commit(
                    art,
                    expected_revision=0,
                    op="create",
                    reason="extract",
                    source_ids=source_ids,
                )
                if cache is not None:
                    cache.put(art)
                link_new(art, graph, cache)
            written += 1
        except Exception as exc:  # noqa: BLE001
            log(f"记忆写入失败： {type(exc).__name__}")
            continue
        # 印象不是只增不减：新证据到了就改旧印象，而不是再堆一条。
        try:
            if cache is not None and str(item.get("level") or "") == "impression":
                with stage("impression.revise"):
                    revise_impression(db, cache, art)
        except Exception as exc:  # noqa: BLE001 - 修订失败不影响已写入的记忆
            log(f"印象修订失败： {type(exc).__name__}")
    return written
