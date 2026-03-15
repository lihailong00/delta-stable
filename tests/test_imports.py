from __future__ import annotations

import importlib
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


class ImportSmokeTests(unittest.TestCase):
    def test_core_modules_import(self) -> None:
        for module_name in (
            "arb",
            "arb.config",
            "arb.logging",
            "arb.models",
            "arb.errors",
        ):
            with self.subTest(module_name=module_name):
                module = importlib.import_module(module_name)
                self.assertIsNotNone(module)


if __name__ == "__main__":
    unittest.main()
