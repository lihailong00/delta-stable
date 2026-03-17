#!/usr/bin/env python
"""Run the funding arbitrage service in local dry-run mode."""

from __future__ import annotations

import argparse
import asyncio
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from arb.execution.executor import PairExecutor
from arb.execution.order_tracker import OrderTracker
from arb.models import MarketType, Order, OrderStatus, Side
from arb.runtime.exchange_manager import LiveExchangeManager, ScanTarget
from arb.runtime.funding_arb_service import FundingArbService
from arb.runtime.pipeline import OpportunityPipeline
from arb.runtime.realtime_scanner import RealtimeScanner
from arb.scanner.funding_scanner import FundingScanner
from arb.workflows.close_position import ClosePositionWorkflow
from arb.workflows.open_position import OpenPositionWorkflow, VenueClients


async def _sleep(_: float) -> None:
    return None


def _snapshot(exchange: str, symbol: str, rate: Decimal) -> dict[str, object]:
    ts = datetime.now(tz=timezone.utc).isoformat()
    return {
        "ticker": {
            "exchange": exchange,
            "symbol": symbol,
            "market_type": "perpetual",
            "bid": "100.0",
            "ask": "100.2",
            "last": "100.1",
            "ts": ts,
        },
        "funding": {
            "exchange": exchange,
            "symbol": symbol,
            "rate": str(rate),
            "predicted_rate": str(rate),
            "next_funding_time": datetime.now(tz=timezone.utc).isoformat(),
            "ts": ts,
        },
        "top_ask_size": "10",
    }


def _filled_order(symbol: str, market_type: MarketType, side: Side, order_id: str, *, reduce_only: bool = False) -> Order:
    return Order(
        exchange="dry-run",
        symbol=symbol,
        market_type=market_type,
        side=side,
        quantity=Decimal("1"),
        price=Decimal("100"),
        status=OrderStatus.FILLED,
        order_id=order_id,
        filled_quantity=Decimal("1"),
        reduce_only=reduce_only,
    )


@dataclass
class _NoopClient:
    symbol: str
    side: Side
    market_type: MarketType
    order_prefix: str
    reduce_only: bool = False
    counter: int = 0

    async def create_order(
        self,
        symbol: str,
        market_type: MarketType,
        side: str,
        quantity: Decimal,
        *,
        price: Decimal | None = None,
        reduce_only: bool = False,
    ) -> Order:
        self.counter += 1
        return _filled_order(
            symbol,
            market_type,
            Side(side),
            f"{self.order_prefix}-{self.counter}",
            reduce_only=reduce_only,
        )

    async def cancel_order(self, order_id: str, symbol: str, market_type: MarketType) -> Order:
        return Order(
            exchange="dry-run",
            symbol=symbol,
            market_type=market_type,
            side=self.side,
            quantity=Decimal("0"),
            price=None,
            status=OrderStatus.CANCELED,
            order_id=order_id,
        )

    async def fetch_order(self, order_id: str, symbol: str, market_type: MarketType) -> Order:
        return _filled_order(symbol, market_type, self.side, order_id, reduce_only=self.reduce_only)

    async def fetch_fills(self, order_id: str, symbol: str, market_type: MarketType) -> tuple[()]:
        return ()


class _SequenceRuntime:
    def __init__(self, exchange: str, symbol: str, funding_sequence: list[Decimal]) -> None:
        self.exchange = exchange
        self.symbol = symbol
        self.funding_sequence = funding_sequence
        self.index = 0

    async def public_ping(self) -> bool:
        return True

    async def fetch_public_snapshot(self, symbol: str, market_type: MarketType) -> dict[str, object]:
        rate = self.funding_sequence[min(self.index, len(self.funding_sequence) - 1)]
        self.index += 1
        return _snapshot(self.exchange, self.symbol, rate)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run funding arbitrage dry-run loop")
    parser.add_argument("--exchange", default=os.getenv("ARB_EXCHANGE", "binance"))
    parser.add_argument("--symbol", default=os.getenv("ARB_SYMBOL", "BTC/USDT"))
    parser.add_argument("--iterations", type=int, default=int(os.getenv("ARB_ITERATIONS", "2")))
    parser.add_argument(
        "--funding-sequence",
        nargs="+",
        default=os.getenv("ARB_FUNDING_SEQUENCE", "0.001 -0.0002").split(),
        help="Funding rates used across iterations.",
    )
    return parser


async def main() -> None:
    args = build_parser().parse_args()
    funding_sequence = [Decimal(item) for item in args.funding_sequence]
    runtime = _SequenceRuntime(args.exchange, args.symbol, funding_sequence)
    manager = LiveExchangeManager({args.exchange: runtime})
    scanner = RealtimeScanner(
        manager,
        FundingScanner(min_net_rate=Decimal("0.0001")),
        OpportunityPipeline(),
        interval=0,
    )
    venue = VenueClients(
        exchange=args.exchange,
        spot_client=_NoopClient(args.symbol, Side.BUY, MarketType.SPOT, "spot"),
        perp_client=_NoopClient(args.symbol, Side.SELL, MarketType.PERPETUAL, "perp"),
    )
    service = FundingArbService(
        scanner=scanner,
        open_workflow=OpenPositionWorkflow(executor=PairExecutor(tracker=OrderTracker(max_polls=1, poll_interval=0, sleep=_sleep))),
        close_workflow=ClosePositionWorkflow(executor=PairExecutor(tracker=OrderTracker(max_polls=1, poll_interval=0, sleep=_sleep))),
        venues={args.exchange: venue},
        manager=manager,
        pipeline=OpportunityPipeline(),
    )
    targets = [ScanTarget(args.exchange, args.symbol, MarketType.PERPETUAL)]

    for index in range(args.iterations):
        result = await service.run_once(targets, dry_run=True)
        print(
            f"iteration={index + 1} opened={len(result['opened'])} "
            f"closed={len(result['closed'])} active={len(result['active'])}"
        )


if __name__ == "__main__":
    asyncio.run(main())
