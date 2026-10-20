"""persona family：人格沉淀文本的校验。"""

from __future__ import annotations

from typing import Any


def validate(payload: dict[str, Any]) -> None:
    """校验一条 persona：只要有非空 text。"""
    if "text" not in payload:
        raise ValueError("persona 缺少必填字段：text")
    text = payload["text"]
    if not isinstance(text, str) or not text.strip():
        raise ValueError("persona.text 必须是非空字符串")
