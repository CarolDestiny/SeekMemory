"""test_persona：稳定 impression 的筛选口径与每周人格沉淀。

覆盖 promote_candidates 的非 impression / 权重 / hits / 年龄四条边界，
compose 的第二人称改写与 TOP_N 上限，persona 未变化时不重复覆盖、
旧 persona 标 merged、lineage 与 ledger 追溯，以及 scope 收敛规则。
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.artifact import Artifact, make
from maintain.persona import TOP_N, compose, distill_persona
from maintain.promote import AGE_DAYS, HITS_BAR, WEIGHT_BAR, promote_candidates
from recall.assemble import build as assemble
from store.cache import Cache
from store.db import DB
from store.ledger import Ledger

TODAY = "2026-10-21"
RECENT = "2026-10-10T10:00:00"


def _memory(
    text: str,
    level: str = "impression",
    weight: float = 2.0,
    hits: int = 4,
    created: str = RECENT,
    scope: str = "private",
    sources: tuple[str, ...] = (),
) -> Artifact:
    """构造一条 memory；impression 默认满足稳定口径，便于单独调边界。"""
    payload = {
        "text": text,
        "level": level,
        "shape": "pattern" if level == "impression" else "point",
        "chrono": "once",
        "about": "other",
    }
    header: dict[str, object] = {
        "strength": {"weight": weight, "hits": hits},
        "scope": scope,
        "time": {"created": created, "updated": created},
    }
    if sources:
        header["lineage"] = {"sources": tuple(sources)}
    return make("memory", payload, **header)


class _PersonaCase(unittest.TestCase):
    """每个用例一个临时数据库与缓存。"""

    def setUp(self) -> None:
        """创建临时库与依赖对象。"""
        self.tmpdir = tempfile.mkdtemp(prefix="seekmemory_persona_")
        self.db = DB(os.path.join(self.tmpdir, "memory.db"))
        self.cache = Cache(self.db)
        self.ledger = Ledger(self.db)

    def tearDown(self) -> None:
        """关闭数据库并删除临时目录。"""
        self.db.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _seed(self, art: Artifact) -> Artifact:
        """同时写库与缓存，模拟一条在线记忆。"""
        self.db.upsert(art)
        self.cache.put(art)
        return art

    def _persona_count(self) -> int:
        """库里 family=persona 的节点总数（含已 merged 的旧版本）。"""
        return self.db.count("persona")


class PromoteTest(_PersonaCase):
    """promote_candidates：只有稳定 impression 才是候选人。"""

    def test_rejects_non_impression_level(self) -> None:
        """scene / fact / 无 level 的记忆即使权重与 hits 再高也不入选。"""
        self._seed(_memory("他今天加班到很晚", "scene", weight=2.0, hits=9))
        self._seed(_memory("他的名字叫吕宇轩", "fact", weight=2.0, hits=9))
        self._seed(make("memory", {"text": "没有层级的旧数据"}))

        self.assertEqual(promote_candidates(self.cache, today=TODAY), [])

    def test_rejects_insufficient_weight(self) -> None:
        """weight < 1.5 不入选；恰好 1.5 是闭区间，可以入选。"""
        low = self._seed(_memory("他偶尔会赖床", weight=WEIGHT_BAR - 0.1))
        self.assertEqual(promote_candidates(self.cache, today=TODAY), [])

        boundary = self._seed(_memory("他有点倔", weight=WEIGHT_BAR))
        self.assertEqual(promote_candidates(self.cache, today=TODAY),
                         [boundary])
        self.assertNotIn(low, promote_candidates(self.cache, today=TODAY))

    def test_rejects_sparse_and_young(self) -> None:
        """hits 不足且存在不到 30 天：不入选；hits 够或年龄够：入选。"""
        self._seed(_memory("他最近有点累", weight=1.6, hits=HITS_BAR - 1,
                           created="2026-10-15T10:00:00"))
        self.assertEqual(promote_candidates(self.cache, today=TODAY), [])

        by_hits = self._seed(_memory("他心软", weight=1.7, hits=HITS_BAR))
        found = promote_candidates(self.cache, today=TODAY)
        self.assertEqual(found, [by_hits])

        by_age = self._seed(_memory("他不会照顾自己", weight=1.6, hits=0,
                                    created="2026-08-01T10:00:00"))
        found = promote_candidates(self.cache, today=TODAY)
        self.assertIn(by_age, found)
        self.assertEqual([art.header.id for art in found],
                         [by_hits.header.id, by_age.header.id])

    def test_age_bar_is_thirty_days(self) -> None:
        """恰好 30 天算稳定，29 天且 hits 不足不算。"""
        young = self._seed(_memory("他今天有点烦", weight=1.8, hits=0,
                                   created="2026-09-22T10:00:00"))
        self.assertEqual(promote_candidates(self.cache, today=TODAY), [])

        mature = self._seed(_memory("他认死理", weight=1.8, hits=0,
                                    created="2026-09-21T10:00:00"))
        found = promote_candidates(self.cache, today=TODAY)
        self.assertEqual([art.header.id for art in found], [mature.header.id])
        self.assertNotIn(young.header.id, [art.header.id for art in found])

    def test_min_hits_override_is_backward_compatible(self) -> None:
        """旧调用 promote_candidates(cache, 10) 的 min_hits 仍可收紧口径。"""
        art = self._seed(_memory("他有点倔", weight=2.0, hits=4))
        self.assertEqual(promote_candidates(self.cache, min_hits=10, today=TODAY), [])
        art = self._seed(_memory("他嘴硬心软", weight=2.0, hits=10))
        self.assertEqual(promote_candidates(self.cache, min_hits=10, today=TODAY), [art])


class ComposeTest(unittest.TestCase):
    """compose：拼成第二人称人格文本。"""

    def test_rewrites_third_person_to_second_person(self) -> None:
        """「他有点倔」改写成「你有点倔。」，后续句子用「你记得」引导。"""
        text = compose([_memory("他有点倔"), _memory("他心软")])
        self.assertEqual(text, "你有点倔。你记得他心软。")

    def test_caps_top_n_and_skips_empty_text(self) -> None:
        """最多取 TOP_N 条，空文本跳过，句子都以第二人称开头。"""
        impressions = [_memory(f"他习惯{index}") for index in range(TOP_N + 2)]
        text = compose(impressions)
        self.assertEqual(text.count("。"), TOP_N)
        self.assertNotIn(f"习惯{TOP_N}", text)
        self.assertTrue(text.startswith("你"))
        self.assertEqual(compose([_memory("")]), "")

    def test_persona_is_first_in_assembled_text(self) -> None:
        """有 persona 时组装头部第一句就是人格，不再补成「你记得你……」。"""
        persona = make("persona", {"text": "你不轻易说重话。"})
        memory = _memory("他加班到很晚", "scene")
        text = assemble([memory, persona], budget=300)
        self.assertTrue(text.startswith("你不轻易说重话。"))
        self.assertNotIn("你记得你", text)


class DistillTest(_PersonaCase):
    """distill_persona：写入 persona、合并旧版本、记账本。"""

    def _seed_three(self) -> tuple[Artifact, Artifact, Artifact]:
        """三条稳定 impression，权重与来源各不相同。"""
        stubborn = self._seed(_memory("他有点倔", weight=2.0, hits=4,
                                      sources=("src_a", "src_b")))
        soft = self._seed(_memory("他心软", weight=1.7, hits=3,
                                  sources=("src_b", "src_c")))
        careless = self._seed(_memory("他不会照顾自己", weight=1.6, hits=3))
        return stubborn, soft, careless

    def test_persona_text_lineage_and_strength(self) -> None:
        """persona 是第二人称文本，derived_from/sources/strength 可追溯。"""
        stubborn, soft, careless = self._seed_three()
        extra = self._seed(_memory("他偶尔赖床", weight=1.5, hits=3,
                                   sources=("src_d",)))

        persona = distill_persona(self.db, self.cache, TODAY)
        self.assertIsNotNone(persona)
        assert persona is not None
        self.assertEqual(persona.header.family, "persona")
        self.assertEqual(persona.header.said_by, "inferred")
        self.assertEqual(persona.payload["text"],
                         "你有点倔。你记得他心软。你知道他不会照顾自己。")
        self.assertEqual(persona.header.lineage.derived_from,
                         (stubborn.header.id, soft.header.id, careless.header.id))
        self.assertNotIn(extra.header.id, persona.header.lineage.derived_from)
        self.assertEqual(persona.header.lineage.sources,
                         ("src_a", "src_b", "src_c"))
        self.assertEqual(persona.header.strength.weight, 2.0)
        self.assertEqual(persona.header.strength.hits, 10)
        self.assertIsNotNone(self.db.get(persona.header.id))
        self.assertEqual([art.header.id for art in self.cache.active("persona")],
                         [persona.header.id])

    def test_unchanged_text_is_not_rewritten(self) -> None:
        """印象没变化时返回旧 persona，不产生新版本、不重复记账。"""
        self._seed_three()
        first = distill_persona(self.db, self.cache, TODAY)
        self.assertIsNotNone(first)
        assert first is not None
        entries = len(self.db.ledger_entries())

        second = distill_persona(self.db, self.cache, TODAY)
        self.assertIsNotNone(second)
        assert second is not None
        self.assertEqual(second.header.id, first.header.id)
        self.assertEqual(second.header.revision, 1)
        self.assertEqual(self._persona_count(), 1)
        self.assertEqual(len(self.db.ledger_entries()), entries)

    def test_old_persona_marked_merged(self) -> None:
        """印象变化后旧 persona 标 merged、移出缓存，新 persona revision +1。"""
        self._seed_three()
        first = distill_persona(self.db, self.cache, TODAY)
        self.assertIsNotNone(first)
        assert first is not None

        self._seed(_memory("他特别爱干净", weight=3.0, hits=6))
        second = distill_persona(self.db, self.cache, TODAY)
        self.assertIsNotNone(second)
        assert second is not None
        self.assertNotEqual(second.header.id, first.header.id)
        self.assertEqual(second.header.revision, 2)

        old = self.db.get(first.header.id)
        self.assertIsNotNone(old)
        assert old is not None
        self.assertEqual(old.header.state, "merged")
        self.assertEqual(old.header.revision, 2)
        self.assertIsNone(self.cache.get(first.header.id))
        self.assertEqual([art.header.id for art in self.cache.active("persona")],
                         [second.header.id])

    def test_no_candidate_keeps_old_persona(self) -> None:
        """没有候选时返回 None，旧 persona 保持 active，账本不新增。"""
        old = self._seed(make("persona", {"text": "旧的人格"}, scope="private"))
        self._seed(_memory("他最近有点累", weight=1.6, hits=1))
        before = len(self.db.ledger_entries())

        self.assertIsNone(distill_persona(self.db, self.cache, TODAY))
        stored = self.db.get(old.header.id)
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored.header.state, "active")
        self.assertIsNotNone(self.cache.get(old.header.id))
        self.assertEqual(len(self.db.ledger_entries()), before)

    def test_ledger_records_merge_and_chain_verifies(self) -> None:
        """沉淀写 op=merge 的账本条目，哈希链可校验。"""
        self._seed_three()
        persona = distill_persona(self.db, self.cache, TODAY)
        self.assertIsNotNone(persona)
        assert persona is not None

        entries = self.db.ledger_entries()
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry["op"], "merge")
        self.assertEqual(entry["entity"], persona.header.id)
        self.assertIsNone(entry["before_hash"])
        self.assertEqual(entry["after_hash"], persona.header.id)
        self.assertIn("沉淀人格", str(entry["reason"]))
        self.assertTrue(self.ledger.verify())

    def test_scope_shared_only_when_all_sources_shared(self) -> None:
        """来源全是 shared 时 persona 才 shared。"""
        self._seed(_memory("他总是嘴硬", scope="shared"))
        self._seed(_memory("他心软", scope="shared"))

        persona = distill_persona(self.db, self.cache, TODAY)
        self.assertIsNotNone(persona)
        assert persona is not None
        self.assertEqual(persona.header.scope, "shared")

    def test_scope_private_when_any_source_private(self) -> None:
        """只要有一条来源是 private，persona 就保持 private。"""
        self._seed(_memory("他总是嘴硬", scope="shared"))
        self._seed(_memory("他心软", scope="private"))

        persona = distill_persona(self.db, self.cache, TODAY)
        self.assertIsNotNone(persona)
        assert persona is not None
        self.assertEqual(persona.header.scope, "private")


if __name__ == "__main__":
    unittest.main(verbosity=2)
