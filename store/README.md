# store/ —— 持久化

## 管什么

SQLite + 内存热数据。**整个项目只有这个目录写 SQL**，换存储只动这里。

- `blobs`：按内容寻址的不可变内容（节点 payload 的 JSON、Source 原文）。
- `nodes`：统一头 + 类型化 payload 的记忆节点，抽象树的父子关系存在 `parent`。
- `edges`：`similar` / `causal` / `temporal` 关系边。
- `sources` / `evidence`：原始对话只追加、不可改；`evidence` 记录结论出自哪条原话。
- `ledger`：append-only 哈希链，每次写入留痕，可重算校验。
- 内存 `Cache`：只装 `state='active'` 的节点，检索路径只读它、不查库。

写入一律走事务（`with conn:`）；坏行/坏 JSON 在读取时返回 `None` 或空 dict（fail-open）。
不 import `astrbot`，也不 import `recall` / `maintain` / `perceive` / `main`。

## 文件表

| 文件 | 行数 | 职责 |
|---|---:|---|
| `__init__.py` | 0 | 空文件，标记 store 包 |
| `schema.sql` | 69 | v3 建表与索引；幂等，每次打开时 `executescript` |
| `db.py` | 220 | `DB`：Artifact ↔ 行转换、节点/边/来源/证据、ledger 底层 SQL |
| `cache.py` | 80 | `Cache`：active 热数据 + family / level 两套索引 |
| `ledger.py` | 50 | `Ledger`：追加日志编排、哈希链重算校验 |
| `README.md` | 52 | 本说明 |

约定与两处必要的补充：

- **`nodes` 多两列**：`revision`、`lineage`。CONTRACT 的 `Header` 含这两个字段，v3 表清单
  没列，不加列 `get()` 就无法无损还原 Artifact。
- **`blob` 内容**：节点存 `payload` 的稳定 JSON（`sort_keys`），sha256 全 64 位 hex 寻址；
  Source 存原文。`content_of()` 的可读文本不进 DB。
- **`edges_of(id)`** 返回 `[(另一端 id, kind, weight)]`，双向命中都返回并去重，
  供 `core/graph.neighbours` 按 kind 过滤。
- **父节点**：`upsert` 识别 `payload["parent"]`；也可调用 `DB.set_parent(id, parent_id)`
  （CONTRACT 未列，供 `core/tree` 使用）。更新时不会把已有 parent 清空。
- **哈希链**：`payload = json.dumps([at, op, entity, before, after, reason], separators=(",", ":"))`，
  `self_hash = sha256(prev_hash + payload)[:16]`。`db.py` 导出 `chain_payload` / `chain_hash`
  供 `ledger.py` 复用。

## 依赖方向

```
main.py / recall/ / perceive/ / maintain/
                  ↓
               store/  ──→  core/artifact.py
```

- `store/` 只依赖 `core/artifact.py`；`core/` 从不反向 import `store/`。
- 目录内部：`db.py` 是最底层，`cache.py`、`ledger.py` 单向依赖 `db.py`，`db.py` 不 import 它们。
- `schema.sql` 只被 `db.py` 读取；其他目录不许出现 SQL。
