"""追加日志的哈希链编排：写入委托 DB，校验时逐条重算。"""

from __future__ import annotations

try:  # 作为 astrbot 插件包的一部分导入
    from .db import DB, chain_hash, chain_payload
except ImportError:  # 作为顶层 store 包导入（脚本 / 测试）
    from db import DB, chain_hash, chain_payload


class Ledger:
    """把 DB 里的 ledger 表包装成可校验的哈希链。"""

    def __init__(self, db: DB) -> None:
        """绑定数据库；不预读日志，verify() 时再取。"""
        self.db = db

    def append(
        self,
        op: str,
        entity: str,
        before: str | None = None,
        after: str | None = None,
        reason: str = "",
    ) -> str:
        """追加一条日志并返回新条目的 self_hash。"""
        self.db.ledger_append(op, entity, before, after, reason)
        return self.last_hash()

    def last_hash(self) -> str:
        """返回链尾哈希；空链返回空串。"""
        return self.db.ledger_last_hash()

    def verify(self) -> bool:
        """重算整条哈希链，检查 prev 连续且 self 正确。"""
        prev = ""
        for row in self.db.ledger_entries():
            payload = chain_payload(
                str(row["at"]),
                str(row["op"]),
                str(row["entity"]),
                row["before_hash"],
                row["after_hash"],
                str(row["reason"]),
            )
            expected = chain_hash(prev, payload)
            if str(row["prev_hash"]) != prev or str(row["self_hash"]) != expected:
                return False
            prev = expected
        return True
