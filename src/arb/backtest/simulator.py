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
    """Replay a funding strategy over historical points.

    `fee_rate` models a one-way trading fee. It is charged once on entry and
    once on exit, not on every funding interval.
    """

    def __init__(
        self,
        *,
        fee_rate: Decimal = Decimal("0"),
        borrow_rate: Decimal = Decimal("0"),
        open_threshold: Decimal | None = None,
        close_threshold: Decimal | None = None,
        hysteresis: Decimal = Decimal("0"),
    ) -> None:
        self.fee_rate = fee_rate
        self.borrow_rate = borrow_rate
        self.open_threshold = open_threshold
        self.close_threshold = close_threshold
        self.hysteresis = hysteresis

    def run(self, points: list[HistoricalPoint], *, position_notional: Decimal) -> BacktestResult:
        if self._uses_thresholds():
            return self._run_threshold_strategy(points, position_notional=position_notional)
        return self._run_always_on(points, position_notional=position_notional)

    def _run_always_on(self, points: list[HistoricalPoint], *, position_notional: Decimal) -> BacktestResult:
        equity = Decimal("0")
        peak = Decimal("0")
        max_drawdown = Decimal("0")
        curve: list[Decimal] = []
        total_liquidity = Decimal("0")

        for index, point in enumerate(points):
            period_pnl = (point.funding_rate - self.borrow_rate) * position_notional
            if index == 0:
                period_pnl -= self.fee_rate * position_notional
            if index == len(points) - 1:
                period_pnl -= self.fee_rate * position_notional
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

    def _run_threshold_strategy(
        self,
        points: list[HistoricalPoint],
        *,
        position_notional: Decimal,
    ) -> BacktestResult:
        open_threshold, close_threshold = self._resolved_thresholds()
        if open_threshold < close_threshold:
            raise ValueError("open_threshold must be greater than or equal to close_threshold")

        equity = Decimal("0")
        peak = Decimal("0")
        max_drawdown = Decimal("0")
        curve: list[Decimal] = []
        total_liquidity = Decimal("0")
        is_open = False

        for point in points:
            total_liquidity += point.liquidity_usd
            if is_open and point.funding_rate < close_threshold:
                equity -= self.fee_rate * position_notional
                is_open = False
            elif not is_open and point.funding_rate >= open_threshold:
                equity -= self.fee_rate * position_notional
                is_open = True

            if is_open:
                equity += (point.funding_rate - self.borrow_rate) * position_notional

            peak = max(peak, equity)
            drawdown = peak - equity
            if drawdown > max_drawdown:
                max_drawdown = drawdown
            curve.append(equity)

        if is_open and points:
            equity -= self.fee_rate * position_notional
            curve[-1] = equity
            peak = max(peak, equity)
            max_drawdown = max(max_drawdown, peak - equity)

        avg_liquidity = total_liquidity / Decimal(len(points)) if points else Decimal("0")
        return BacktestResult(
            total_return=equity,
            max_drawdown=max_drawdown,
            average_liquidity_usd=avg_liquidity,
            equity_curve=curve,
        )

    def _uses_thresholds(self) -> bool:
        return self.open_threshold is not None or self.close_threshold is not None

    def _resolved_thresholds(self) -> tuple[Decimal, Decimal]:
        open_threshold = self.open_threshold or Decimal("0")
        if self.close_threshold is not None:
            close_threshold = self.close_threshold
        else:
            close_threshold = open_threshold - self.hysteresis
        return open_threshold, close_threshold
