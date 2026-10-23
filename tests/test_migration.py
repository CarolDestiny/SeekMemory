"""Old database migration regressions."""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from store.db import DB  # noqa: E402


class MigrationTest(unittest.TestCase):
    def test_old_nodes_and_versions_are_upgraded_without_losing_history(self) -> None:
        path = os.path.join(tempfile.mkdtemp(prefix="seekmem_migration_"), "old.db")
        con = sqlite3.connect(path)
        con.execute(
            "CREATE TABLE nodes (id TEXT PRIMARY KEY, family TEXT, level TEXT, "
            "parent TEXT, blob TEXT, state TEXT, scope TEXT, strength TEXT, time TEXT, "
            "said_by TEXT, shareable TEXT, created_at TEXT, updated_at TEXT)"
        )
        con.execute(
            "CREATE TABLE versions (entity TEXT, revision INTEGER, blob TEXT, at TEXT, "
            "PRIMARY KEY(entity, revision))"
        )
        con.execute("CREATE TABLE blobs (hash TEXT PRIMARY KEY, content TEXT, at TEXT)")
        payload = '{"text": "legacy fact", "level": "fact"}'
        con.execute("INSERT INTO blobs(hash, content, at) VALUES(?, ?, ?)",
                    ("h1", payload, "2024-01-01T00:00:00"))
        con.execute(
            "INSERT INTO nodes(id, family, level, parent, blob, state, scope, strength, "
            "time, said_by, shareable, created_at, updated_at) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("n1", "memory", "fact", None, "h1", "active", "private", "{}",
             "{}", "u1", "private_only", "2024-01-01T00:00:00",
             "2024-01-01T00:00:00"),
        )
        con.execute(
            "INSERT INTO versions(entity, revision, blob, at) VALUES(?, ?, ?, ?)",
            ("n1", 1, "h1", "2024-01-01T00:00:00"),
        )
        con.commit()
        con.close()

        db = DB(path)
        self.addCleanup(db.close)
        cols = {row[1] for row in db.conn.execute("PRAGMA table_info(nodes)")}
        self.assertTrue({"subject_id", "revision", "lineage"} <= cols)
        rows = db.conn.execute(
            "SELECT entity, revision, op FROM artifact_versions"
        ).fetchall()
        self.assertEqual([(str(row[0]), int(row[1]), str(row[2])) for row in rows],
                         [("n1", 1, "migrate")])
        history = db.history("n1")
        self.assertEqual(history[0]["payload"]["text"], "legacy fact")
        art = db.get("n1")
        self.assertIsNotNone(art)
        self.assertEqual(art.header.subject_id, "")
        self.assertEqual(art.header.revision, 1)


if __name__ == "__main__":
    unittest.main()
