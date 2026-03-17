"""离线示例：单交易所跑一次资金费率扫描。

运行：
PYTHONPATH=src uv run python examples/single_exchange_scan.py
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal

from arb.models import MarketType
from arb.runtime import LiveExchangeManager, OpportunityPipeline, RealtimeScanner, ScanTarget
from arb.scanner.funding_scanner import FundingScanner


class _StaticRuntime:
    async def public_ping(self) -> bool:
        return True

    async def fetch_public_snapshot(self, symbol: str, market_type: MarketType) -> dict[str, object]:
        ts = datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat()
        return {
            "ticker": {
                "exchange": "binance",
                "symbol": symbol,
                "market_type": market_type.value,
                "bid": "100.0",
                "ask": "100.2",
                "last": "100.1",
                "ts": ts,
            },
            "funding": {
                "exchange": "binance",
                "symbol": symbol,
                "rate": "0.0008",
                "predicted_rate": "0.0008",
                "next_funding_time": datetime(2026, 1, 1, 8, tzinfo=timezone.utc).isoformat(),
                "ts": ts,
            },
            "liquidity_usd": "250000",
        }


async def main() -> None:
    manager = LiveExchangeManager({"binance": _StaticRuntime()})
    scanner = FundingScanner(
        trading_fee_rate=Decimal("0.0002"),
        slippage_rate=Decimal("0.0001"),
        min_net_rate=Decimal("0.0001"),
        min_liquidity_usd=Decimal("1000"),
    )
    pipeline = OpportunityPipeline()
    realtime = RealtimeScanner(manager, scanner, pipeline)
    result = await realtime.scan_once(
        [ScanTarget("binance", "BTC/USDT", MarketType.PERPETUAL)],
        dry_run=True,
    )

    print("opportunities")
    for item in result["opportunities"]:
        print(item)
    print("output")
    for line in result["output"]:
        print(line)


if __name__ == "__main__":
    asyncio.run(main())
