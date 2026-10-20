"""SQLite 持久化层：Artifact 与数据行的双向转换、追加日志写入。

这是整个项目唯一写 SQL 的文件；异常交给调用方 fail-open 处理。
"""

from __future__ import annotations

import dataclasses
import datetime
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

try:  # 作为 astrbot 插件包的一部分导入
    from ..core.artifact import Artifact, Header, Lineage, Strength, TimeSpan
except ImportError:  # 作为顶层 store 包导入（脚本 / 测试）
    from core.artifact import Artifact, Header, Lineage, Strength, TimeSpan

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
_SELECT = ("SELECT n.*, b.content AS blob_content FROM nodes n "
           "LEFT JOIN blobs b ON b.hash = n.blob")
_UPSERT = (
    "INSERT INTO nodes(id, family, level, parent, blob, state, scope, strength, time, "
    "said_by, shareable, created_at, updated_at, revision, lineage) "
    "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
    "family=excluded.family, level=excluded.level, "
    "parent=COALESCE(excluded.parent, nodes.parent), blob=excluded.blob, "
    "state=excluded.state, scope=excluded.scope, strength=excluded.strength, "
    "time=excluded.time, said_by=excluded.said_by, shareable=excluded.shareable, "
    "revision=excluded.revision, lineage=excluded.lineage, updated_at=excluded.updated_at, "
    "created_at=CASE WHEN nodes.created_at = '' THEN excluded.created_at "
    "ELSE nodes.created_at END"
)


def _now() -> str:
    """当前本地时间，精确到秒。"""
    return datetime.datetime.now().isoformat(timespec="seconds")


def _dump(value: Any) -> str:
    """把 dataclass / dict / 元组序列化成稳定的 JSON 文本。"""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        value = dataclasses.asdict(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _loads(raw: Any) -> dict[str, Any]:
    """容错地把 TEXT 列读成 dict；坏数据退回空 dict。"""
    try:
        data = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _pick(cls: type, data: dict[str, Any]) -> dict[str, Any]:
    """只保留 cls 的 dataclass 字段，容忍多出来的键。"""
    names = {f.name for f in dataclasses.fields(cls)}
    return {k: v for k, v in data.items() if k in names}


def chain_payload(at: str, op: str, entity: str, before: str | None,
                  after: str | None, reason: str) -> str:
    """把一条日志的业务字段拼成哈希输入；顺序固定，便于重算。"""
    return json.dumps([at, op, entity, before, after, reason],
                      ensure_ascii=False, separators=(",", ":"))


def chain_hash(prev_hash: str, payload: str) -> str:
    """哈希链单步：sha256(prev_hash + payload) 取前 16 位。"""
    return hashlib.sha256((prev_hash + payload).encode("utf-8")).hexdigest()[:16]


class DB:
    """SQLite 门面：节点、边、来源、证据与日志。"""

    def __init__(self, path: str) -> None:
        """打开数据库、设置 WAL，并保证表结构存在。"""
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript("PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;")
        self.conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

    def upsert(self, art: Artifact) -> None:
        """写入或更新一条记忆；payload 按内容寻址存入 blobs。"""
        h, now = art.header, _now()
        content = _dump(art.payload)
        blob = hashlib.sha256(content.encode("utf-8")).hexdigest()
        level, parent = art.payload.get("level"), art.payload.get("parent")
        args = (
            h.id, h.family, level if isinstance(level, str) else None,
            parent if isinstance(parent, str) else None, blob, h.state, h.scope,
            _dump(h.strength), _dump(h.time), h.said_by, h.shareable,
            h.time.created or now, h.time.updated or now, int(h.revision),
            _dump(h.lineage),
        )
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO blobs(hash, content, at) VALUES(?, ?, ?)",
                (blob, content, now))
            self.conn.execute(_UPSERT, args)

    def get(self, node_id: str) -> Artifact | None:
        """按 id 取一条完整记忆；不存在或数据损坏时返回 None。"""
        row = self.conn.execute(_SELECT + " WHERE n.id = ?", (node_id,)).fetchone()
        return self._to_artifact(row)

    def list(self, family: str | None = None,
             state: str | None = None) -> list[Artifact]:
        """按 family / state 过滤列出记忆，按创建时间排序。"""
        sql, args = _SELECT, []
        for column, value in (("family", family), ("state", state)):
            if value is not None:
                sql += (" WHERE " if not args else " AND ") + f"n.{column} = ?"
                args.append(value)
        rows = self.conn.execute(sql + " ORDER BY n.created_at, n.id", args).fetchall()
        return [art for art in map(self._to_artifact, rows) if art is not None]

    def set_parent(self, node_id: str, parent_id: str | None) -> None:
        """单独调整抽象树父子关系（CONTRACT 未列出，供 core/tree 使用）。"""
        with self.conn:
            self.conn.execute(
                "UPDATE nodes SET parent = ?, updated_at = ? WHERE id = ?",
                (parent_id, _now(), node_id))

    def count(self, family: str | None = None) -> int:
        """统计节点行数，可按 family 过滤。"""
        row = self.conn.execute(
            "SELECT COUNT(*) AS c FROM nodes WHERE ? IS NULL OR family = ?",
            (family, family)).fetchone()
        return int(row["c"]) if row is not None else 0

    def add_edge(self, src: str, dst: str, kind: str, weight: float) -> None:
        """新增或更新一条关系边。"""
        with self.conn:
            self.conn.execute(
                "INSERT INTO edges(src, dst, kind, weight) VALUES(?, ?, ?, ?) "
                "ON CONFLICT(src, dst, kind) DO UPDATE SET weight=excluded.weight",
                (src, dst, kind, float(weight)))

    def edges_of(self, node_id: str) -> list[tuple[str, str, float]]:
        """与该节点相连的边：(另一端 id, kind, weight)，双向都会返回。"""
        rows = self.conn.execute(
            "SELECT dst AS other, kind, weight FROM edges WHERE src = ? "
            "UNION SELECT src AS other, kind, weight FROM edges WHERE dst = ?",
            (node_id, node_id)).fetchall()
        return [(str(r["other"]), str(r["kind"]), float(r["weight"])) for r in rows]

    def add_source(self, sid: str, umo: str, at: str, role: str, text: str,
                   flags: dict[str, Any]) -> None:
        """追加一条不可变的原始来源；同 id 只保留第一次写入。"""
        blob = hashlib.sha256(text.encode("utf-8")).hexdigest()
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO blobs(hash, content, at) VALUES(?, ?, ?)",
                (blob, text, at))
            self.conn.execute(
                "INSERT OR IGNORE INTO sources(id, umo, at, role, blob, flags) "
                "VALUES(?, ?, ?, ?, ?, ?)",
                (sid, umo, at, role, blob, _dump(flags)))

    def link_evidence(self, node_id: str, source_id: str) -> None:
        """把一条记忆挂到一条来源上；重复调用无副作用。"""
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO evidence(node, source) VALUES(?, ?)",
                (node_id, source_id))

    def ledger_last_hash(self) -> str:
        """返回日志链尾的 self_hash；空链返回空串。"""
        row = self.conn.execute(
            "SELECT self_hash FROM ledger ORDER BY seq DESC LIMIT 1").fetchone()
        return str(row["self_hash"]) if row is not None else ""

    def ledger_append(self, op: str, entity: str, before: str | None,
                      after: str | None, reason: str) -> None:
        """追加一条日志，哈希链在此闭合。"""
        at = _now()
        prev = self.ledger_last_hash()
        payload = chain_payload(at, op, entity, before, after, reason)
        with self.conn:
            self.conn.execute(
                "INSERT INTO ledger(at, op, entity, before_hash, after_hash, reason, "
                "prev_hash, self_hash) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                (at, op, entity, before, after, reason, prev, chain_hash(prev, payload)))

    def ledger_entries(self) -> list[sqlite3.Row]:
        """按 seq 升序导出日志原始行，供 store/ledger.py 重算校验。"""
        return self.conn.execute(
            "SELECT at, op, entity, before_hash, after_hash, reason, prev_hash, "
            "self_hash FROM ledger ORDER BY seq").fetchall()

    def close(self) -> None:
        """关闭连接。"""
        self.conn.close()

    @staticmethod
    def _to_artifact(row: sqlite3.Row | None) -> Artifact | None:
        """把查询行还原成 Artifact；损坏行返回 None（fail-open）。"""
        if row is None or not row["blob_content"]:
            return None
        try:
            lineage = _pick(Lineage, _loads(row["lineage"]))
            for key in ("sources", "derived_from"):  # JSON 数组还原成契约里的 tuple
                lineage[key] = tuple(lineage.get(key) or ())
            header = Header(
                id=str(row["id"]), family=str(row["family"]),
                revision=int(row["revision"] or 1), state=str(row["state"]),
                scope=str(row["scope"]), lineage=Lineage(**lineage),
                strength=Strength(**_pick(Strength, _loads(row["strength"]))),
                time=TimeSpan(**_pick(TimeSpan, _loads(row["time"]))),
                said_by=str(row["said_by"]), shareable=str(row["shareable"]))
            payload = json.loads(row["blob_content"])
        except (TypeError, ValueError, KeyError):
            return None
        return Artifact(header=header, payload=payload if isinstance(payload, dict) else {})
