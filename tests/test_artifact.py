"""test_artifact：Artifact 原语的构造、校验、修订与可读文本。

覆盖六个 family 的 make/validate/content_of、缺字段报错、revision 递增
与旧版本保留，以及 fact/scene/detail/impression 四个 level。
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.artifact import (
    Artifact,
    Header,
    Strength,
    content_of,
    make,
    revise,
    validate,
)

FAMILY_PAYLOADS = {
    "memory": {"text": "他加班到很晚", "level": "scene"},
    "example": {"user": "你好", "assistant": "嗨"},
    "persona": {"text": "我嘴硬心软"},
    "media": {"type": "video", "title": "大肥鱼是怎么来的", "url": "https://x"},
    "secret": {"ref": "s_1", "shadow_text": "有件事你答应过别人不说"},
    "designated": {"text": "密码是 123", "trigger": "那个东西"},
}

# family -> [(缺的字段, 剩下的合法 payload)]
MISSING_FIELDS = {
    "memory": [
        ("text", {"level": "scene"}),
        ("level", {"text": "一件事"}),
    ],
    "example": [
        ("user", {"assistant": "嗨"}),
        ("assistant", {"user": "你好"}),
    ],
    "persona": [("text", {})],
    "media": [
        ("type", {"title": "标题", "url": "https://x"}),
        ("title", {"type": "video", "url": "https://x"}),
        ("url", {"type": "video", "title": "标题"}),
    ],
    "secret": [
        ("ref", {"shadow_text": "影子"}),
        ("shadow_text", {"ref": "s_1"}),
    ],
    "designated": [
        ("text", {"trigger": "那个东西"}),
        ("trigger", {"text": "密码"}),
    ],
}

LEVELS = ("fact", "scene", "detail", "impression")


class _TempDirCase(unittest.TestCase):
    """每个用例一个临时目录，跑完清理（本文件不落盘，仅统一隔离约定）。"""

    def setUp(self) -> None:
        """创建临时目录。"""
        self.tmpdir = tempfile.mkdtemp(prefix="seekmemory_artifact_")

    def tearDown(self) -> None:
        """删除临时目录。"""
        shutil.rmtree(self.tmpdir, ignore_errors=True)


class MakeValidateTest(_TempDirCase):
    """make / validate：六个 family 的必填字段与默认头。"""

    def test_make_and_validate_all_families(self) -> None:
        """六个 family 都能构造并通过校验，默认头符合契约。"""
        seen_ids = set()
        for family, payload in FAMILY_PAYLOADS.items():
            with self.subTest(family=family):
                art = make(family, payload)
                validate(art)  # 不抛异常即通过
                self.assertEqual(art.header.family, family)
                self.assertEqual(art.payload, payload)
                self.assertEqual(art.header.revision, 1)
                self.assertEqual(art.header.state, "active")
                self.assertEqual(art.header.scope, "private")
                self.assertEqual(art.header.said_by, "owner")
                self.assertEqual(art.header.shareable, "private_only")
                self.assertTrue(art.header.id.startswith("n_"))
                self.assertTrue(art.header.time.created)
                self.assertTrue(art.header.time.updated)
                self.assertNotIn(art.header.id, seen_ids)
                seen_ids.add(art.header.id)

    def test_make_coerces_nested_header_dicts(self) -> None:
        """header 里的 strength/lineage/time 传 dict 时自动转成 dataclass。"""
        art = make(
            "memory",
            {"text": "他加班到很晚", "level": "scene"},
            strength={"weight": 2.0, "hits": 3},
            lineage={"sources": ("s_1",), "derived_from": ("n_x",)},
            time={"created": "2024-01-01T00:00:00", "updated": "2024-01-02T00:00:00"},
        )
        self.assertIsInstance(art.header.strength, Strength)
        self.assertEqual(art.header.strength.weight, 2.0)
        self.assertEqual(art.header.strength.hits, 3)
        self.assertEqual(art.header.lineage.sources, ("s_1",))
        self.assertEqual(art.header.time.created, "2024-01-01T00:00:00")

    def test_missing_required_field_raises(self) -> None:
        """缺任一必填字段时 validate 抛 ValueError。"""
        for family, cases in MISSING_FIELDS.items():
            for missing, payload in cases:
                with self.subTest(family=family, missing=missing):
                    art = make(family, payload)
                    with self.assertRaises(ValueError):
                        validate(art)

    def test_empty_string_field_raises(self) -> None:
        """必填文本字段为空串时同样抛 ValueError。"""
        cases = [
            ("memory", {"text": "   ", "level": "scene"}),
            ("example", {"user": "", "assistant": "嗨"}),
            ("persona", {"text": "  "}),
            ("media", {"type": "video", "title": "", "url": "https://x"}),
            ("secret", {"ref": "s_1", "shadow_text": ""}),
            ("designated", {"text": "", "trigger": "那个东西"}),
        ]
        for family, payload in cases:
            with self.subTest(family=family):
                with self.assertRaises(ValueError):
                    validate(make(family, payload))

    def test_unknown_family_raises(self) -> None:
        """构造与校验都拒绝未知 family。"""
        with self.assertRaises(ValueError):
            make("diary", {"text": "x"})
        art = Artifact(header=Header(id="n_bad", family="diary"), payload={"text": "x"})
        with self.assertRaises(ValueError):
            validate(art)

    def test_non_dict_payload_raises(self) -> None:
        """payload 不是 dict 时 validate 抛 ValueError。"""
        art = Artifact(header=Header(id="n_bad", family="memory"), payload=[])
        with self.assertRaises(ValueError):
            validate(art)

    def test_all_levels_supported(self) -> None:
        """fact / scene / detail / impression 四个 level 全部合法。"""
        for level in LEVELS:
            with self.subTest(level=level):
                art = make("memory", {"text": f"{level} 的内容", "level": level})
                validate(art)
                self.assertEqual(content_of(art), f"{level} 的内容")

    def test_illegal_level_raises(self) -> None:
        """非法 level（拼错、大小写不对、空串）抛 ValueError。"""
        for level in ("episode", "Fact", "", "  ", "facts"):
            with self.subTest(level=level):
                art = make("memory", {"text": "一件事", "level": level})
                with self.assertRaises(ValueError):
                    validate(art)


class ContentOfTest(_TempDirCase):
    """content_of：每个 family 的可读文本。"""

    def test_content_of_all_families(self) -> None:
        """六种 family 的 content_of 都返回预期文本。"""
        cases = [
            ("memory", {"text": "他加班到很晚", "level": "scene"}, "他加班到很晚"),
            ("example", {"user": "你好", "assistant": "嗨"}, "你好 → 嗨"),
            ("persona", {"text": "我嘴硬心软"}, "我嘴硬心软"),
            (
                "media",
                {
                    "type": "video",
                    "title": "大肥鱼是怎么来的",
                    "url": "https://x",
                    "summary": "讲大肥鱼由来的视频",
                },
                "讲大肥鱼由来的视频",
            ),
            ("secret", {"ref": "s_1", "shadow_text": "有件事你答应过别人不说"}, "有件事你答应过别人不说"),
            ("designated", {"text": "密码是 123", "trigger": "那个东西"}, "密码是 123"),
        ]
        for family, payload, expected in cases:
            with self.subTest(family=family):
                self.assertEqual(content_of(make(family, payload)), expected)

    def test_media_falls_back_to_title(self) -> None:
        """media 没有 summary 时退回 title。"""
        art = make(
            "media",
            {"type": "music", "title": "一首歌", "url": "https://x"},
        )
        self.assertEqual(content_of(art), "一首歌")

    def test_content_of_missing_field_raises(self) -> None:
        """未校验的坏 Artifact 调 content_of 会抛 ValueError。"""
        broken = [
            make("memory", {"level": "scene"}),
            make("example", {"assistant": "嗨"}),
            make("persona", {}),
            make("secret", {"ref": "s_1"}),
            make("designated", {"trigger": "那个东西"}),
        ]
        for art in broken:
            with self.subTest(family=art.header.family):
                with self.assertRaises(ValueError):
                    content_of(art)


class ReviseTest(_TempDirCase):
    """revise：revision 递增、旧版本与溯源信息保留。"""

    def test_revise_increments_revision_and_keeps_old_version(self) -> None:
        """revise 后 revision +1，旧 Artifact 原封不动（历史可回溯）。"""
        art = make(
            "memory",
            {"text": "旧文本", "level": "scene"},
            lineage={"sources": ("s_1",)},
            strength={"weight": 1.2, "hits": 2},
            time={"created": "2024-01-01T00:00:00", "updated": "2024-01-02T00:00:00"},
        )
        first = revise(art)
        second = revise(first, {"text": "新文本", "level": "detail"})

        self.assertEqual(art.header.revision, 1)
        self.assertEqual(first.header.revision, 2)
        self.assertEqual(second.header.revision, 3)
        for version in (art, first, second):
            self.assertEqual(version.header.id, art.header.id)
            self.assertEqual(version.header.time.created, "2024-01-01T00:00:00")
            self.assertEqual(version.header.lineage.sources, ("s_1",))
        self.assertEqual(art.payload["text"], "旧文本")
        self.assertEqual(first.payload["text"], "旧文本")
        self.assertEqual(second.payload["text"], "新文本")
        self.assertGreaterEqual(first.header.time.updated, art.header.time.updated)
        self.assertGreaterEqual(second.header.time.updated, first.header.time.updated)

    def test_revise_with_header_overrides(self) -> None:
        """revise 可改 state/scope/strength，payload 不传时沿用旧内容。"""
        art = make("memory", {"text": "一件事", "level": "scene"})
        revised = revise(
            art,
            state="forgotten",
            scope="shared",
            strength={"weight": 2.5},
        )
        self.assertEqual(revised.header.state, "forgotten")
        self.assertEqual(revised.header.scope, "shared")
        self.assertEqual(revised.header.strength.weight, 2.5)
        self.assertEqual(revised.payload, art.payload)
        self.assertEqual(revised.header.revision, 2)
        self.assertEqual(art.header.revision, 1)

    def test_revise_does_not_mutate_original(self) -> None:
        """frozen dataclass：revise 返回新对象，原对象字段保持不变。"""
        art = make("persona", {"text": "我嘴硬心软"})
        revised = revise(art, {"text": "我也会心软"})
        self.assertIsNot(revised, art)
        self.assertEqual(art.payload["text"], "我嘴硬心软")
        self.assertEqual(revised.payload["text"], "我也会心软")
        self.assertEqual(art.header.revision, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
