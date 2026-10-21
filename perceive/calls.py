"""记忆调用日志：每轮记一条"这轮要不要翻记忆、翻了几条"。

只记结构，不记内容——用来回答"什么情况下会调用记忆"，以及调完之后有没有用。
写 JSONL，超过 4MB 滚一份备份；任何失败都静默。
"""

from __future__ import annotations

import datetime
import json
import os

MAX_BYTES = 4 * 1024 * 1024


def log_call(path: str, umo: str, info: dict) -> None:
    """追加一条调用记录：会话类型、唤起档位、命中条数、注入字数。"""
    try:
        if not path:
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path) and os.path.getsize(path) > MAX_BYTES:
            os.replace(path, path + ".1")
        kind = str(umo or "").split(":")
        rec = {
            "t": datetime.datetime.now().isoformat(timespec="seconds"),
            "kind": kind[1] if len(kind) > 1 else "unknown",
            "mode": str(info.get("mode") or "strict"),
            "picked": int(info.get("picked") or 0),
            "pinned": int(info.get("pinned") or 0),
            "chars": int(info.get("chars") or 0),
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 - 记录失败不影响回复
        pass
