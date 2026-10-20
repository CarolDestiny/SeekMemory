-- SeekMemory v3 存储结构。
-- 幂等：每次打开数据库时由 db.py 用 executescript 执行。
-- created_at/updated_at 之后追加的 revision、lineage 两列，是 CONTRACT 中
-- Header 要求的字段，v3 表清单未列出，缺了就无法无损往返。

CREATE TABLE IF NOT EXISTS blobs (
    hash    TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ledger (
    seq         INTEGER PRIMARY KEY AUTOINCREMENT,
    at          TEXT NOT NULL,
    op          TEXT NOT NULL,
    entity      TEXT NOT NULL,
    before_hash TEXT,
    after_hash  TEXT,
    reason      TEXT NOT NULL DEFAULT '',
    prev_hash   TEXT NOT NULL DEFAULT '',
    self_hash   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS nodes (
    id         TEXT PRIMARY KEY,
    family     TEXT NOT NULL,
    level      TEXT,
    parent     TEXT,
    blob       TEXT NOT NULL,
    state      TEXT NOT NULL DEFAULT 'active',
    scope      TEXT NOT NULL DEFAULT 'private',
    strength   TEXT NOT NULL DEFAULT '{}',
    time       TEXT NOT NULL DEFAULT '{}',
    said_by    TEXT NOT NULL DEFAULT 'owner',
    shareable  TEXT NOT NULL DEFAULT 'private_only',
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT '',
    revision   INTEGER NOT NULL DEFAULT 1,
    lineage    TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS edges (
    src    TEXT NOT NULL,
    dst    TEXT NOT NULL,
    kind   TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 1.0,
    PRIMARY KEY (src, dst, kind)
);

CREATE TABLE IF NOT EXISTS sources (
    id    TEXT PRIMARY KEY,
    umo   TEXT NOT NULL,
    at    TEXT NOT NULL,
    role  TEXT NOT NULL,
    blob  TEXT NOT NULL,
    flags TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS evidence (
    node   TEXT NOT NULL,
    source TEXT NOT NULL,
    PRIMARY KEY (node, source)
);

CREATE INDEX IF NOT EXISTS idx_nodes_family_state ON nodes(family, state);
CREATE INDEX IF NOT EXISTS idx_nodes_level ON nodes(level);
CREATE INDEX IF NOT EXISTS idx_nodes_parent ON nodes(parent);
CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src);
CREATE INDEX IF NOT EXISTS idx_evidence_node ON evidence(node);
