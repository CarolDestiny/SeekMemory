"""secret family：被动听到的秘密——只留影子，不存正文。"""

from __future__ import annotations

from typing import Any


def _need(payload: dict[str, Any], key: str) -> str:
    if key not in payload:
        raise ValueError(f"secret 缺少必填字段：{key}")
    value = payload[key]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"secret 字段 {key} 必须是非空字符串")
    return value


def validate(payload: dict[str, Any]) -> None:
    """校验一条 secret：ref 指向内容，shadow_text 是可全局注入的影子句。"""
    _need(payload, "ref")
    _need(payload, "shadow_text")
    hint = payload.get("hint")
    if hint is not None and not isinstance(hint, str):
        raise ValueError("secret.hint 必须是字符串")
