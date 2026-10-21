"""recall.designated：指定记忆的交付协议（ISSUE-0004）。

DESIGN §7.1 的三条硬条件：只在私聊、必须命中触发词、命中后才给出正文。
群里问或私聊未触发时一条都不注入；交付后把 payload["given"] 写成时间戳，
避免同一条内容被反复归还。
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

try:  # 作为 astrbot 插件包的一部分导入
    from ..core.artifact import Artifact, revise
except ImportError:  # 作为顶层 recall 包导入（脚本 / 测试）
    from core.artifact import Artifact, revise

_SPLIT = re.compile(r"[\s,，、/|;；]+")


def triggers_of(art: Artifact) -> list[str]:
    """取触发词：支持字符串（空格/逗号/顿号分隔）与列表两种写法。"""
    raw = art.payload.get("trigger")
    if isinstance(raw, (list, tuple, set)):
        parts = [str(item) for item in raw]
    else:
        parts = _SPLIT.split(str(raw or ""))
    return [part.strip() for part in parts if part.strip()]


def _compact(text: Any) -> str:
    """去掉空白后比较，避免“那个 东西”和“那个东西”匹配不上。"""
    return "".join(str(text or "").split())


def matches(art: Artifact, text: str) -> bool:
    """当前消息是否命中任一触发词（精确子串，去空白，不做模糊/同义）。"""
    message = _compact(text)
    return bool(message) and any(_compact(word) in message for word in triggers_of(art))


def already_given(art: Artifact) -> bool:
    """given 已被写成 bool 或时间字符串，都算交付过。"""
    return bool(art.payload.get("given"))


def is_private(event: Any) -> bool:
    """AstrBot 事件的私聊判断；取不到时按群聊处理（保守，不交付正文）。"""
    try:
        return bool(event.is_private_chat())
    except Exception:  # noqa: BLE001 - 事件实现差异不能拖垮注入
        return False


def deliverable(art: Artifact, text: str, private: bool) -> bool:
    """非 designated 不受限；designated 必须私聊 + 命中触发词 + 尚未交付。"""
    if art.header.family != "designated":
        return True
    return bool(private) and not already_given(art) and matches(art, text)


def mark_given(db: Any, cache: Any, arts: list[Artifact], block: str,
               now: str | None = None) -> int:
    """把本轮确实注入了正文的 designated 标成已给，返回写回条数。

    只处理正文真的出现在 block 里的条目：预算裁剪可能丢掉候选，不能因为
    进过 picked 就记成已给。单条写回失败只跳过该条（fail-open）。
    """
    stamp = now or datetime.now().isoformat(timespec="seconds")
    done = 0
    for art in arts:
        if art.header.family != "designated" or already_given(art):
            continue
        body = " ".join(str(art.payload.get("text") or "").split())[:24]
        if not body or body not in block:
            continue
        try:
            updated = revise(art, payload={**art.payload, "given": stamp})
            db.commit(updated, expected_revision=art.header.revision, op="deliver",
                      reason="designated delivered",
                      source_ids=tuple(art.header.lineage.sources))
            cache.put(updated)
        except Exception:  # noqa: BLE001
            continue
        done += 1
    return done
