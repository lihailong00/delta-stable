#!/usr/bin/env python
"""Run the funding arbitrage service in local dry-run mode."""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated

import typer

from arb.cli_support import normalize_multi_value_options
from arb.execution.executor import PairExecutor
from arb.execution.order_tracker import OrderTracker
from arb.models import MarketType, Order, OrderStatus, Side
from arb.runtime.exchange_manager import LiveExchangeManager, ScanTarget
from arb.runtime.funding_arb_service import FundingArbService
from arb.runtime.pipeline import OpportunityPipeline
from arb.runtime.realtime_scanner import RealtimeScanner
from arb.runtime.supervisor import RuntimeSupervisor
from arb.scanner.funding_scanner import FundingScanner
from arb.workflows.close_position import ClosePositionWorkflow
from arb.workflows.open_position import OpenPositionWorkflow, VenueClients

_OPTION_NAMES = {
    "--exchange",
    "--symbol",
    "--iterations",
    "--supervised",
    "--max-restarts",
    "--funding-sequence",
    "--help",
}
_MULTI_VALUE_OPTIONS = {
    "--funding-sequence",
}


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
        del symbol, market_type
        rate = self.funding_sequence[min(self.index, len(self.funding_sequence) - 1)]
        self.index += 1
        return _snapshot(self.exchange, self.symbol, rate)


async def _run_dry_run(
    *,
    exchange: str,
    symbol: str,
    iterations: int,
    supervised: bool,
    max_restarts: int,
    funding_sequence: list[Decimal],
) -> None:
    runtime = _SequenceRuntime(exchange, symbol, funding_sequence)
    manager = LiveExchangeManager({exchange: runtime})
    scanner = RealtimeScanner(
        manager,
        FundingScanner(min_net_rate=Decimal("0.0001")),
        OpportunityPipeline(),
        interval=0,
    )
    venue = VenueClients(
        exchange=exchange,
        spot_client=_NoopClient(symbol, Side.BUY, MarketType.SPOT, "spot"),
        perp_client=_NoopClient(symbol, Side.SELL, MarketType.PERPETUAL, "perp"),
    )
    service = FundingArbService(
        scanner=scanner,
        open_workflow=OpenPositionWorkflow(
            executor=PairExecutor(tracker=OrderTracker(max_polls=1, poll_interval=0, sleep=_sleep))
        ),
        close_workflow=ClosePositionWorkflow(
            executor=PairExecutor(tracker=OrderTracker(max_polls=1, poll_interval=0, sleep=_sleep))
        ),
        venues={exchange: venue},
        manager=manager,
        pipeline=OpportunityPipeline(),
    )
    targets = [ScanTarget(exchange, symbol, MarketType.PERPETUAL)]
    state = {"iteration": 0}

    async def run_iteration() -> dict[str, object]:
        state["iteration"] += 1
        result = await service.run_once(targets, dry_run=True)
        print(
            f"iteration={state['iteration']} opened={len(result['opened'])} "
            f"closed={len(result['closed'])} active={len(result['active'])}"
        )
        return result

    if supervised:
        supervisor = RuntimeSupervisor(run_iteration, max_restarts=max_restarts)
        await supervisor.run_forever(iterations=iterations)
        snapshot = supervisor.snapshot()
        print(
            "supervisor "
            f"completed={snapshot['completed_iterations']} restarts={snapshot['restart_count']} "
            f"healthy={snapshot['healthy']}"
        )
        return

    for _ in range(iterations):
        await run_iteration()


def main(
    exchange: Annotated[str, typer.Option("--exchange")] = os.getenv("ARB_EXCHANGE", "binance"),
    symbol: Annotated[str, typer.Option("--symbol")] = os.getenv("ARB_SYMBOL", "BTC/USDT"),
    iterations: Annotated[int, typer.Option("--iterations")] = int(os.getenv("ARB_ITERATIONS", "2")),
    supervised: Annotated[bool, typer.Option("--supervised")] = False,
    max_restarts: Annotated[int, typer.Option("--max-restarts")] = int(os.getenv("ARB_MAX_RESTARTS", "2")),
    funding_sequence: Annotated[list[str] | None, typer.Option("--funding-sequence")] = None,
) -> None:
    sequence_values = funding_sequence or os.getenv("ARB_FUNDING_SEQUENCE", "0.001 -0.0002").split()
    asyncio.run(
        _run_dry_run(
            exchange=exchange,
            symbol=symbol,
            iterations=iterations,
            supervised=supervised,
            max_restarts=max_restarts,
            funding_sequence=[Decimal(item) for item in sequence_values],
        )
    )


def run(argv: list[str] | None = None) -> None:
    normalized_argv = normalize_multi_value_options(
        list(sys.argv[1:] if argv is None else argv),
        multi_value_options=_MULTI_VALUE_OPTIONS,
        option_names=_OPTION_NAMES,
    )
    original_argv = sys.argv[:]
    try:
        sys.argv = [original_argv[0], *normalized_argv]
        typer.run(main)
    finally:
        sys.argv = original_argv


if __name__ == "__main__":
    run()
