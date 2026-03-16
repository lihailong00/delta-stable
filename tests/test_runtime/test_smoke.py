from __future__ import annotations

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arb.runtime.smoke import SmokeRunner


class _HealthyRuntime:
    async def public_ping(self) -> bool:
        return True

    async def validate_private_access(self):
        return {"USDT": "100"}


class _BrokenPrivateRuntime:
    async def public_ping(self) -> bool:
        return True

    async def validate_private_access(self):
        raise RuntimeError("permission denied")


class _BrokenPublicRuntime:
    async def public_ping(self) -> bool:
        raise RuntimeError("timeout")

    async def validate_private_access(self):
        return {}


class SmokeRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_smoke(self) -> None:
        runner = SmokeRunner({"binance": _HealthyRuntime(), "gate": _BrokenPublicRuntime()})
        results = await runner.run_many(["binance", "gate"])
        self.assertTrue(results[0].public_ok)
        self.assertFalse(results[1].public_ok)

    async def test_private_smoke(self) -> None:
        runner = SmokeRunner({"okx": _HealthyRuntime(), "bybit": _BrokenPrivateRuntime()})
        results = await runner.run_many(["okx", "bybit"], private=True)
        self.assertTrue(results[0].private_ok)
        self.assertFalse(results[1].private_ok)

    async def test_summary_lines(self) -> None:
        runner = SmokeRunner({"binance": _HealthyRuntime()})
        results = await runner.run_many(["binance"], private=True)
        lines = runner.summarize(results)
        self.assertIn("public=ok", lines[0])
        self.assertIn("private=ok", lines[0])


if __name__ == "__main__":
    unittest.main()
