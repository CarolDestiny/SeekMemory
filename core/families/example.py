"""example family：对话语料样本的校验。"""

from __future__ import annotations

from typing import Any


def _need(payload: dict[str, Any], key: str) -> str:
    if key not in payload:
        raise ValueError(f"example 缺少必填字段：{key}")
    value = payload[key]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"example 字段 {key} 必须是非空字符串")
    return value


def validate(payload: dict[str, Any]) -> None:
    """校验一条 example：一轮 user/assistant 对话，可选 tags。"""
    _need(payload, "user")
    _need(payload, "assistant")
    tags = payload.get("tags")
    if tags is None:
        return
    if not isinstance(tags, (list, tuple)):
        raise ValueError("example.tags 必须是字符串列表")
    if not all(isinstance(tag, str) for tag in tags):
        raise ValueError("example.tags 必须全部是字符串")
