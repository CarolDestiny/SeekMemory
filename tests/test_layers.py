from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from layers import ALL_LAYERS, files_for  # noqa: E402


class LayerMapTest(unittest.TestCase):
    def test_every_test_file_has_a_layer(self) -> None:
        mapped = set(files_for("all"))
        actual = {path.name for path in ROOT.glob("tests/test_*.py")}
        self.assertEqual(sorted(actual - mapped), [])
        self.assertEqual(sorted(mapped - actual), [])

    def test_every_layer_has_at_least_one_test(self) -> None:
        for layer in ALL_LAYERS:
            self.assertTrue(files_for(layer), layer)


if __name__ == "__main__":
    unittest.main()
