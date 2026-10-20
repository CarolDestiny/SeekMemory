"""designated family：「帮我记一下」的指定记忆校验。"""

from __future__ import annotations

from typing import Any


def _need(payload: dict[str, Any], key: str) -> str:
    if key not in payload:
        raise ValueError(f"designated 缺少必填字段：{key}")
    value = payload[key]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"designated 字段 {key} 必须是非空字符串")
    return value


def validate(payload: dict[str, Any]) -> None:
    """校验一条 designated：text 是内容，trigger 是取回时必须触发的词。

    取回还要求私聊场景，由上层权限模块负责，不在这里校验。
    """
    _need(payload, "text")
    _need(payload, "trigger")
    given = payload.get("given")
    if given is not None and not isinstance(given, (bool, str)):
        raise ValueError("designated.given 必须是 bool 或时间字符串")
    owner = payload.get("owner")
    if owner is not None and not isinstance(owner, str):
        raise ValueError("designated.owner 必须是字符串")
