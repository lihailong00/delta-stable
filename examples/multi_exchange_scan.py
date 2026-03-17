"""离线示例：多交易所并发扫描并查看 metrics。

运行：
PYTHONPATH=src uv run python examples/multi_exchange_scan.py
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal

from arb.market.schemas import MarketSnapshot
from arb.models import MarketType
from arb.models import FundingRate, Ticker
from arb.monitoring.metrics import MetricsRegistry
from arb.runtime import LiveExchangeManager, OpportunityPipeline, RealtimeScanner, ScanTarget
from arb.scanner.funding_scanner import FundingScanner


class _StaticRuntime:
    def __init__(self, exchange: str, rate: str, liquidity_usd: str, *, funding_interval_hours: int) -> None:
        self.exchange = exchange
        self.rate = rate
        self.liquidity_usd = liquidity_usd
        self.funding_interval_hours = funding_interval_hours

    async def public_ping(self) -> bool:
        return True

    async def fetch_public_snapshot(self, symbol: str, market_type: MarketType) -> MarketSnapshot:
        ts = datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat()
        return MarketSnapshot(
            ticker=Ticker(
                exchange=self.exchange,
                symbol=symbol,
                market_type=market_type,
                bid=Decimal("100.0"),
                ask=Decimal("100.3"),
                last=Decimal("100.15"),
                ts=ts,
            ),
            funding=FundingRate(
                exchange=self.exchange,
                symbol=symbol,
                rate=Decimal(self.rate),
                predicted_rate=Decimal(self.rate),
                funding_interval_hours=self.funding_interval_hours,
                next_funding_time=datetime(2026, 1, 1, 8, tzinfo=timezone.utc),
                ts=ts,
            ),
            liquidity_usd=Decimal(self.liquidity_usd),
        )


async def main() -> None:
    metrics = MetricsRegistry()
    messages: list[str] = []
    manager = LiveExchangeManager(
        {
            "binance": _StaticRuntime("binance", "0.0007", "350000", funding_interval_hours=8),
            "okx": _StaticRuntime("okx", "0.0005", "240000", funding_interval_hours=4),
            "bybit": _StaticRuntime("bybit", "0.0002", "500000", funding_interval_hours=1),
        }
    )
    scanner = FundingScanner(
        trading_fee_rate=Decimal("0.0002"),
        slippage_rate=Decimal("0.0001"),
        min_net_rate=Decimal("0.0001"),
        min_liquidity_usd=Decimal("10000"),
    )
    pipeline = OpportunityPipeline(metrics=metrics, publisher=messages.append)
    realtime = RealtimeScanner(manager, scanner, pipeline, interval=0)

    result = await realtime.scan_once(
        [
            ScanTarget("binance", "BTC/USDT", MarketType.PERPETUAL),
            ScanTarget("okx", "BTC/USDT", MarketType.PERPETUAL),
            ScanTarget("bybit", "ETH/USDT", MarketType.PERPETUAL),
        ],
        dry_run=True,
    )

    print("ranked output")
    for line in result["output"]:
        print(line)
    print("note: ranking is based on interval-normalized annualized net rate")
    print("metrics")
    print(metrics.snapshot())


if __name__ == "__main__":
    asyncio.run(main())
