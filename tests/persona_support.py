"""以真实 Source/CAS 准备 #15 的独立行为证据。"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.artifact import Lineage, Strength, make
from core.source import Source
from store.cache import Cache
from store.db import DB


class PersonaCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = DB(str(Path(self.temp.name) / "memory.db"))
        self.addCleanup(self.db.close)
        self.cache = Cache(self.db)
        self.seq = 0

    def seed(self, art):
        self.db.commit(art, expected_revision=0, op="create",
                       source_ids=art.header.lineage.sources)
        self.cache.put(art)
        return art

    def episode(self, kind="respond_emotion", confidence=0.95, **payload):
        self.seq += 1
        n = self.seq
        user = Source(f"u{n}", f"t{n}", f"session:{n}", f"person{n}", "user",
                      "虚构隐私：许澄，栖云城，橙色纸鹤", "2026-10-23T10:00:00")
        reply = Source(f"a{n}", f"t{n}", user.session_id, "bot", "assistant",
                       "先休息一下，我陪你梳理", user.at, reply_to=user.id)
        self.db.append_sources([user, reply])
        return self.seed(make("memory", {
            "text": f"original scene {n}", "level": "scene", "bot_behavior": kind,
            "bot_action": "许澄在栖云城说橙色纸鹤", **payload},
            subject_id=user.speaker_id,
            lineage=Lineage(sources=(user.id, reply.id)),
            strength=Strength(confidence=confidence)))

    def three(self, kind="respond_emotion"):
        return [self.episode(kind) for _ in range(3)]
