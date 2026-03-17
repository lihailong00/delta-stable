from __future__ import annotations
import pytest
import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import sys
from pathlib import Path
pytestmark = pytest.mark.asyncio
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from arb.models import MarketType
from arb.monitoring.alerts import AlertManager
from arb.monitoring.health import HealthChecker
from arb.monitoring.metrics import MetricsRegistry
from arb.runtime.exchange_manager import LiveExchangeManager, ScanTarget
from arb.runtime.pipeline import OpportunityPipeline
from arb.runtime.protocols import SnapshotRuntimeProtocol
from arb.runtime.realtime_scanner import RealtimeScanner
from arb.scanner.funding_scanner import FundingOpportunity, FundingScanner

def _snapshot(exchange: str, symbol: str, rate: str='0.0005') -> dict[str, object]:
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat()
    return {'ticker': {'exchange': exchange, 'symbol': symbol, 'market_type': 'perpetual', 'bid': '100.0', 'ask': '101.0', 'last': '100.5', 'ts': ts}, 'funding': {'exchange': exchange, 'symbol': symbol, 'rate': rate, 'predicted_rate': rate, 'next_funding_time': datetime(2026, 1, 1, 8, tzinfo=timezone.utc).isoformat(), 'ts': ts}, 'top_ask_size': '12'}

class _BarrierRuntime:

    def __init__(self, name: str, start_event: asyncio.Event, other_event: asyncio.Event) -> None:
        self.name = name
        self.start_event = start_event
        self.other_event = other_event

    async def public_ping(self) -> bool:
        return True

    async def fetch_public_snapshot(self, symbol: str, market_type: MarketType) -> dict[str, object]:
        self.start_event.set()
        await asyncio.wait_for(self.other_event.wait(), timeout=0.2)
        return _snapshot(self.name, symbol)

class _FlakyRuntime:

    def __init__(self) -> None:
        self.calls = 0

    async def public_ping(self) -> bool:
        return True

    async def fetch_public_snapshot(self, symbol: str, market_type: MarketType) -> dict[str, object]:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError('temporary disconnect')
        return _snapshot('binance', symbol)

class _StaticRuntime:

    async def public_ping(self) -> bool:
        return True

    async def fetch_public_snapshot(self, symbol: str, market_type: MarketType) -> dict[str, object]:
        return _snapshot('binance', symbol)

class _MemoryRepository:

    def __init__(self) -> None:
        self.tickers = []
        self.funding = []
        self.workflows = []

    def save_ticker(self, ticker) -> None:
        self.tickers.append(ticker)

    def save_funding(self, funding) -> None:
        self.funding.append(funding)

    def save_workflow_state(self, **payload) -> None:
        self.workflows.append(payload)

class TestRealtimeScanner:

    async def test_runtime_protocol_compatibility_for_manager(self) -> None:
        assert isinstance(_StaticRuntime(), SnapshotRuntimeProtocol)
        assert isinstance(_FlakyRuntime(), SnapshotRuntimeProtocol)

    async def test_manager_collects_snapshots_in_parallel(self) -> None:
        first_started = asyncio.Event()
        second_started = asyncio.Event()
        manager = LiveExchangeManager({'binance': _BarrierRuntime('binance', first_started, second_started), 'okx': _BarrierRuntime('okx', second_started, first_started)}, health_checker=HealthChecker())
        snapshots = await manager.collect_snapshots([ScanTarget('binance', 'BTC/USDT', MarketType.PERPETUAL), ScanTarget('okx', 'ETH/USDT', MarketType.PERPETUAL)])
        assert len(snapshots) == 2
        assert {item['ticker']['exchange'] for item in snapshots} == {'binance', 'okx'}

    async def test_scanner_recovers_after_runtime_error(self) -> None:
        alerts = []
        alert_manager = AlertManager(alerts.append)
        manager = LiveExchangeManager({'binance': _FlakyRuntime()}, alert_manager=alert_manager, health_checker=HealthChecker(max_staleness=timedelta(seconds=1)))
        repository = _MemoryRepository()
        pipeline = OpportunityPipeline(repository=repository, metrics=MetricsRegistry(), publisher=lambda message: None)
        scanner = RealtimeScanner(manager, FundingScanner(min_net_rate=Decimal('0.0001')), pipeline, interval=0)
        results = await scanner.run([ScanTarget('binance', 'BTC/USDT', MarketType.PERPETUAL)], iterations=2, dry_run=True)
        assert len(alerts) == 1
        assert 'temporary disconnect' in alerts[0].message
        assert len(results[1]['opportunities']) == 1
        assert len(repository.tickers) == 1
        assert len(repository.funding) == 1

    async def test_pipeline_formats_dry_run_output(self) -> None:
        repository = _MemoryRepository()
        messages = []
        pipeline = OpportunityPipeline(repository=repository, metrics=MetricsRegistry(), publisher=messages.append)
        scanner = FundingScanner(min_net_rate=Decimal('0.0001'))
        manager = LiveExchangeManager({'binance': _StaticRuntime()})
        realtime = RealtimeScanner(manager, scanner, pipeline, interval=0)
        result = await realtime.scan_once([ScanTarget('binance', 'BTC/USDT', MarketType.PERPETUAL)], dry_run=True)
        assert result['output'][0].startswith('DRY-RUN ')
        assert len(messages) == 1
        assert repository.tickers[0].exchange == 'binance'
        assert repository.funding[0].symbol == 'BTC/USDT'

    async def test_manager_enforces_single_slot_per_symbol(self) -> None:
        manager = LiveExchangeManager({'binance': _StaticRuntime()})
        assert manager.acquire_slot('funding:binance:BTC/USDT')
        assert not manager.acquire_slot('funding:binance:BTC/USDT')
        manager.release_slot('funding:binance:BTC/USDT')
        assert manager.acquire_slot('funding:binance:BTC/USDT')

    async def test_scanner_selects_only_inactive_opportunities(self) -> None:
        scanner = RealtimeScanner(
            LiveExchangeManager({'binance': _StaticRuntime()}),
            FundingScanner(min_net_rate=Decimal('0.0001')),
            OpportunityPipeline(metrics=MetricsRegistry()),
            interval=0,
        )
        opportunities = [
            FundingOpportunity(exchange='binance', symbol='BTC/USDT', gross_rate=Decimal('0.001'), net_rate=Decimal('0.001'), annualized_net_rate=Decimal('1.095'), spread_bps=Decimal('5'), liquidity_usd=Decimal('1000')),
            FundingOpportunity(exchange='okx', symbol='ETH/USDT', gross_rate=Decimal('0.0008'), net_rate=Decimal('0.0008'), annualized_net_rate=Decimal('0.876'), spread_bps=Decimal('4'), liquidity_usd=Decimal('1000')),
        ]
        selected = scanner.select_opportunities(opportunities, active_keys={'binance:BTC/USDT'})
        assert len(selected) == 1
        assert selected[0].exchange == 'okx'
