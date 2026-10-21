"""待抽取缓冲：把当天的话攒起来，落盘保存，攒够了再交给抽取。

只负责"攒"和"存"，不调模型、不碰数据库。重启后从文件恢复，
这样白天说的话不会因为容器重启就丢掉。
"""

from __future__ import annotations

import json
import os
import time

KEEP = 200


class Buffer:
    def __init__(self, path: str = "") -> None:
        self.path = str(path or "")
        self.items: list[tuple[str, str, str, str]] = []  # (umo, sender, role, text)
        self.last_ts = 0.0
        self.load()

    def add(self, umo: str, text: str, sender: str = "") -> None:
        """收一条用户消息，立刻落盘。sender 用于区分群里是谁说的。"""
        text = str(text or "").strip()
        if not text:
            return
        self.items.append((str(umo or ""), str(sender or ""), "user", text))
        self.items = self.items[-KEEP:]
        self.last_ts = time.time()
        self.save()

    def should_flush(self, idle_seconds: float, min_items: int) -> bool:
        """攒够条数、且安静够久，才值得花一次模型调用。"""
        if not self.items:
            return False
        return len(self.items) >= max(1, min_items) and (
            time.time() - self.last_ts >= idle_seconds
        )

    def take(self) -> list[tuple[str, str, str, str]]:
        """取走全部待抽取内容并清空（已落盘）。"""
        items = self.items
        self.items = []
        self.save()
        return items

    def save(self) -> None:
        """写存档；失败只丢持久化，不影响聊天。"""
        if not self.path:
            return
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump({"last": self.last_ts, "items": self.items},
                          f, ensure_ascii=False)
        except Exception:  # noqa: BLE001
            pass

    def load(self) -> None:
        """从存档恢复；没有或坏了就当空的。"""
        if not self.path:
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:  # noqa: BLE001
            return
        if not isinstance(data, dict):
            return
        raw = data.get("items")
        if isinstance(raw, list):
            kept = []
            for row in raw:
                if not isinstance(row, (list, tuple)):
                    continue
                if len(row) == 4:
                    kept.append((str(row[0]), str(row[1]), str(row[2]), str(row[3])))
                elif len(row) == 3:  # 兼容旧存档
                    kept.append((str(row[0]), "", str(row[1]), str(row[2])))
            self.items = kept[-KEEP:]
        try:
            self.last_ts = float(data.get("last") or 0.0)
        except (TypeError, ValueError):
            self.last_ts = 0.0
