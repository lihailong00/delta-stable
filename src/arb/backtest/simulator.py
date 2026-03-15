"""Funding backtest simulator."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from arb.backtest.loader import HistoricalPoint


@dataclass(slots=True, frozen=True)
class BacktestResult:
    total_return: Decimal
    max_drawdown: Decimal
    average_liquidity_usd: Decimal
    equity_curve: list[Decimal]


class FundingBacktester:
    """Replay a funding strategy over historical points."""

    def __init__(self, *, fee_rate: Decimal = Decimal("0"), borrow_rate: Decimal = Decimal("0")) -> None:
        self.fee_rate = fee_rate
        self.borrow_rate = borrow_rate

    def run(self, points: list[HistoricalPoint], *, position_notional: Decimal) -> BacktestResult:
        equity = Decimal("0")
        peak = Decimal("0")
        max_drawdown = Decimal("0")
        curve: list[Decimal] = []
        total_liquidity = Decimal("0")

        for point in points:
            period_pnl = (point.funding_rate - self.fee_rate - self.borrow_rate) * position_notional
            equity += period_pnl
            peak = max(peak, equity)
            drawdown = peak - equity
            if drawdown > max_drawdown:
                max_drawdown = drawdown
            curve.append(equity)
            total_liquidity += point.liquidity_usd

        avg_liquidity = total_liquidity / Decimal(len(points)) if points else Decimal("0")
        return BacktestResult(
            total_return=equity,
            max_drawdown=max_drawdown,
            average_liquidity_usd=avg_liquidity,
            equity_curve=curve,
        )
