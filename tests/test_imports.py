from __future__ import annotations
import importlib
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

class TestImportSmoke:

    def test_core_modules_import(self) -> None:
        for module_name in ('arb', 'arb.config', 'arb.config.live', 'arb.logging', 'arb.models', 'arb.errors', 'arb.safety.runtime'):
            module = importlib.import_module(module_name)
            assert module is not None
