"""recall.scope：按 scope 决定一条记忆能不能进入当前会话的候选池。

private 只给归属会话；shared 全员可见；shadow 全员可见但只保留影子，
正文由 recall.assemble 遮蔽。归属 umo 按以下顺序推导：

1. payload 里写入时记录的 owner_umo / umo（新数据）；
2. lineage.sources 反查 sources.umo（由调用方注入 lookup，本模块不碰 SQL）；
3. said_by 本身是 umo（形如 ``napcat:FriendMessage:123``）。

三条都取不到时按“只给 owner_umo 会话”处理；owner_umo 也未配置则 private
不可见（保守优先，避免把别人的私聊注入给所有人）。
"""

from __future__ import annotations

from typing import Callable, Iterable

try:  # 作为 astrbot 插件包的一部分导入
    from ..core.artifact import Artifact
except ImportError:  # 作为顶层 recall 包导入（脚本 / 测试）
    from core.artifact import Artifact

OWNER_KEYS = ("owner_umo", "umo")
Lookup = Callable[[str], str]


def owner_of(art: Artifact, lookup: Lookup | None = None) -> str:
    """推导一条记忆的归属 umo；没有归属信息时返回空串。"""
    payload = art.payload if isinstance(art.payload, dict) else {}
    for key in OWNER_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for source in art.header.lineage.sources or ():
        if lookup is None:
            break
        try:
            umo = lookup(str(source))
        except Exception:  # noqa: BLE001 - 单条来源坏了不影响其他条目
            continue
        if umo:
            return str(umo)
    said_by = str(art.header.said_by or "")
    return said_by if ":" in said_by else ""


def visible(pool: Iterable[Artifact], umo: str, owner_umo: str = "",
            lookup: Lookup | None = None) -> list[Artifact]:
    """Return the global memory pool while preserving explicit delivery scope.

    Session provenance remains useful for evidence and disclosure weighting, but
    ordinary private/shared/shadow memory is global. ``secret`` and explicitly
    delivered ``designated`` artifacts keep their stricter delivery boundary.
    """
    viewer = str(umo or "")
    fallback = str(owner_umo or "")
    kept: list[Artifact] = []
    for art in pool:
        family = str(art.header.family or "")
        if family == "secret":
            continue
        if family == "designated":
            own = owner_of(art, lookup)
            if own:
                if own != viewer:
                    continue
            elif not fallback or viewer != fallback:
                continue
        kept.append(art)
    return kept
