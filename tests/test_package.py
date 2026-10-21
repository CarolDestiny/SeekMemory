"""Verify the installable archive boundary and run its isolated backend."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.package_plugin import package_plugin  # noqa: E402


class PackageTests(unittest.TestCase):
    def setUp(self) -> None:
        """Create a checkout with real backend files and minimal built assets."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "checkout"
        self.root.mkdir()
        self.output = Path(self.temp.name) / "dist"
        for name in (
            "main.py",
            "metadata.yaml",
            "_conf_schema.json",
            "LICENSE-MIT",
            "LICENSE-APACHE",
            "store/schema.sql",
        ):
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        for directory in ("core", "store", "recall", "perceive", "maintain", "webui"):
            for source in (ROOT / directory).rglob("*.py"):
                target = self.root / source.relative_to(ROOT)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
        self.view = self.root / "views/memory"
        (self.view / "assets").mkdir(parents=True)
        (self.view / "index.html").write_text(
            '<link href="./assets/app.css"><script src="./assets/app.js"></script>',
            encoding="utf-8",
        )
        (self.view / "LICENSES.md").write_text("Fixture licenses", encoding="utf-8")
        (self.view / "ASSET-LICENSES.txt").write_text(
            "Fixture asset licenses", encoding="utf-8"
        )
        (self.view / "assets/app.js").write_text(
            "console.log('production')", encoding="utf-8"
        )
        (self.view / "assets/app.css").write_text(
            "body { color: black }", encoding="utf-8"
        )
        (self.root / ".gitignore").write_text("/views/\n", encoding="utf-8")
        for name in (
            ".env",
            "core/private.db",
            "tests/fixture.py",
            "dashboard/src/demo.ts",
        ):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("not distributable", encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(
            ["git", "-C", str(self.root), "add", "."], check=True, capture_output=True
        )
        (self.root / "core/untracked.py").write_text(
            "local_only = True", encoding="utf-8"
        )

    def test_runtime_allowlist_and_reproducible_checksum(self) -> None:
        """Exclude development and local files while preserving runtime resources."""
        archive = package_plugin(self.root, self.output)
        first = archive.read_bytes()
        with ZipFile(archive) as bundle:
            names = set(bundle.namelist())
            self.assertTrue(
                {"main.py", "store/schema.sql", "views/memory/index.html"} <= names
            )
            self.assertTrue(
                {"LICENSE-MIT", "LICENSE-APACHE", "views/memory/LICENSES.md"} <= names
            )
            self.assertFalse(
                {
                    ".env",
                    "core/private.db",
                    "core/untracked.py",
                    "tests/fixture.py",
                    "dashboard/src/demo.ts",
                }
                & names
            )
            self.assertIsNone(bundle.testzip())
        self.assertEqual(first, package_plugin(self.root, self.output).read_bytes())
        self.assertEqual(
            (self.output / "SHA256SUMS").read_text(encoding="utf-8"),
            f"{hashlib.sha256(first).hexdigest()}  {archive.name}\n",
        )

    def test_missing_runtime_resource_fails(self) -> None:
        """Do not emit a ZIP when the SQL schema is missing."""
        (self.root / "store/schema.sql").unlink()
        with self.assertRaisesRegex(ValueError, "Missing or empty"):
            package_plugin(self.root, self.output)
        self.assertFalse(self.output.exists())

    def test_missing_or_unbuilt_frontend_fails(self) -> None:
        """Require production assets, license notices, and resolved entry URLs."""
        for name in (
            "index.html",
            "LICENSES.md",
            "ASSET-LICENSES.txt",
            "assets/app.js",
            "assets/app.css",
        ):
            with self.subTest(name=name):
                path = self.view / name
                contents = path.read_bytes()
                path.unlink()
                with self.assertRaises(ValueError):
                    package_plugin(self.root, self.output)
                path.write_bytes(contents)
        (self.view / "index.html").write_text(
            '<script src="/src/main.tsx"></script>', encoding="utf-8"
        )
        with self.assertRaisesRegex(ValueError, "relative production assets"):
            package_plugin(self.root, self.output)

    def test_tag_must_match_metadata(self) -> None:
        """A tag must describe the version actually contained in the package."""
        (self.root / "metadata.yaml").write_text(
            'version: "1.2.3-rc.1"\n', encoding="utf-8"
        )
        package_plugin(self.root, self.output, "v1.2.3-rc.1")
        with self.assertRaisesRegex(ValueError, "does not match"):
            package_plugin(self.root, self.output, "v1.2.3")

    def test_missing_font_reference_fails(self) -> None:
        """A valid entry must not hide missing secondary CSS assets."""
        (self.view / "assets/app.css").write_text(
            '@font-face { src: url("./missing.woff2") }', encoding="utf-8"
        )
        with self.assertRaisesRegex(ValueError, "CSS references an unpackaged"):
            package_plugin(self.root, self.output)

    def test_source_maps_and_mock_bundles_fail(self) -> None:
        """Prevent development data and source maps from entering release assets."""
        source_map = self.view / "assets/app.js.map"
        source_map.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Unexpected build asset"):
            package_plugin(self.root, self.output)
        source_map.unlink()
        (self.view / "assets/app.js").write_text(
            'const id = "mock_memory_001"', encoding="utf-8"
        )
        with self.assertRaisesRegex(ValueError, "Development code"):
            package_plugin(self.root, self.output)

    def test_backend_runs_from_extracted_archive(self) -> None:
        """Run the smoke test against extracted files without the source checkout."""
        archive = package_plugin(self.root, self.output)
        installed = Path(self.temp.name) / "installed"
        with ZipFile(archive) as bundle:
            bundle.extractall(installed)
        # The test harness is external to the shipped ZIP.
        (installed / "tests").mkdir()
        shutil.copyfile(ROOT / "tests/test_smoke.py", installed / "tests/test_smoke.py")
        result = subprocess.run(
            [
                sys.executable,
                "-X",
                "utf8",
                "-I",
                str(installed / "tests/test_smoke.py"),
            ],
            cwd=installed,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
