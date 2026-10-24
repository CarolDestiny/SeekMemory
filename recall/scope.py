"""recall.scope：普通记忆进入全局候选池，表达程度由披露规则决定。

private、shared、shadow 可参与跨会话检索；只有允许全文披露时才注入正文。
secret 不进入普通上下文，designated 保留指定会话的交付限制。
指定交付的归属会话按以下顺序推导：

1. payload 里写入时记录的 owner_umo / umo（新数据）；
2. lineage.sources 反查 sources.umo（由调用方注入 lookup，本模块不碰 SQL）；
3. said_by 本身是 umo（形如 ``napcat:FriendMessage:123``）。

三条都取不到时只允许配置的 owner_umo 会话；未配置则不交付指定记忆。
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
