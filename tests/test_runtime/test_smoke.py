from __future__ import annotations
import pytest
import sys
from pathlib import Path
pytestmark = pytest.mark.asyncio
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from arb.runtime.protocols import SmokeRuntimeProtocol
from arb.runtime.smoke import SmokeRunner

class _HealthyRuntime:

    async def public_ping(self) -> bool:
        return True

    async def validate_private_access(self):
        return {'USDT': '100'}

class _BrokenPrivateRuntime:

    async def public_ping(self) -> bool:
        return True

    async def validate_private_access(self):
        raise RuntimeError('permission denied')

class _BrokenPublicRuntime:

    async def public_ping(self) -> bool:
        raise RuntimeError('timeout')

    async def validate_private_access(self):
        return {}

class TestSmokeRunner:

    async def test_runtime_protocol_compatibility_for_smoke(self) -> None:
        assert isinstance(_HealthyRuntime(), SmokeRuntimeProtocol)
        assert isinstance(_BrokenPrivateRuntime(), SmokeRuntimeProtocol)

    async def test_public_smoke(self) -> None:
        runner = SmokeRunner({'binance': _HealthyRuntime(), 'gate': _BrokenPublicRuntime()})
        results = await runner.run_many(['binance', 'gate'])
        assert results[0].public_ok
        assert not results[1].public_ok

    async def test_private_smoke(self) -> None:
        runner = SmokeRunner({'okx': _HealthyRuntime(), 'bybit': _BrokenPrivateRuntime()})
        results = await runner.run_many(['okx', 'bybit'], private=True)
        assert results[0].private_ok
        assert not results[1].private_ok

    async def test_summary_lines(self) -> None:
        runner = SmokeRunner({'binance': _HealthyRuntime()})
        results = await runner.run_many(['binance'], private=True)
        lines = runner.summarize(results)
        assert 'public=ok' in lines[0]
        assert 'private=ok' in lines[0]
