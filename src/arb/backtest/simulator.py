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
    funding_pnl: Decimal = Decimal("0")
    open_fee_cost: Decimal = Decimal("0")
    close_fee_cost: Decimal = Decimal("0")
    rebalance_fee_cost: Decimal = Decimal("0")
    borrow_cost: Decimal = Decimal("0")


class FundingBacktester:
    """Replay a funding strategy over historical points.

    `fee_rate` models a one-way trading fee. It is charged once on entry and
    once on exit, not on every funding interval.
    """

    def __init__(
        self,
        *,
        fee_rate: Decimal | None = None,
        open_fee_rate: Decimal | None = None,
        close_fee_rate: Decimal | None = None,
        rebalance_fee_rate: Decimal = Decimal("0"),
        borrow_rate: Decimal = Decimal("0"),
        rebalance_threshold_bps: Decimal | None = None,
        open_threshold: Decimal | None = None,
        close_threshold: Decimal | None = None,
        hysteresis: Decimal = Decimal("0"),
    ) -> None:
        fallback_fee_rate = fee_rate or Decimal("0")
        self.fee_rate = fallback_fee_rate
        self.open_fee_rate = fallback_fee_rate if open_fee_rate is None else open_fee_rate
        self.close_fee_rate = fallback_fee_rate if close_fee_rate is None else close_fee_rate
        self.rebalance_fee_rate = rebalance_fee_rate
        self.borrow_rate = borrow_rate
        self.rebalance_threshold_bps = rebalance_threshold_bps
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
        funding_pnl = Decimal("0")
        open_fee_cost = Decimal("0")
        close_fee_cost = Decimal("0")
        rebalance_fee_cost = Decimal("0")
        borrow_cost = Decimal("0")
        previous_price: Decimal | None = None

        for index, point in enumerate(points):
            if previous_price is not None and self._should_rebalance(previous_price, point.price):
                rebalance_cost = self.rebalance_fee_rate * position_notional
                rebalance_fee_cost += rebalance_cost
                equity -= rebalance_cost
                previous_price = point.price
            elif previous_price is None:
                previous_price = point.price

            period_pnl = point.funding_rate * position_notional
            funding_pnl += period_pnl
            borrow_period_cost = self.borrow_rate * position_notional
            borrow_cost += borrow_period_cost
            period_pnl -= borrow_period_cost
            if index == 0:
                fee_cost = self.open_fee_rate * position_notional
                open_fee_cost += fee_cost
                period_pnl -= fee_cost
            if index == len(points) - 1:
                fee_cost = self.close_fee_rate * position_notional
                close_fee_cost += fee_cost
                period_pnl -= fee_cost
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
            funding_pnl=funding_pnl,
            open_fee_cost=open_fee_cost,
            close_fee_cost=close_fee_cost,
            rebalance_fee_cost=rebalance_fee_cost,
            borrow_cost=borrow_cost,
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
        funding_pnl = Decimal("0")
        open_fee_cost = Decimal("0")
        close_fee_cost = Decimal("0")
        rebalance_fee_cost = Decimal("0")
        borrow_cost = Decimal("0")
        reference_price: Decimal | None = None

        for point in points:
            total_liquidity += point.liquidity_usd
            if is_open and point.funding_rate < close_threshold:
                fee_cost = self.close_fee_rate * position_notional
                close_fee_cost += fee_cost
                equity -= fee_cost
                is_open = False
                reference_price = None
            elif not is_open and point.funding_rate >= open_threshold:
                fee_cost = self.open_fee_rate * position_notional
                open_fee_cost += fee_cost
                equity -= fee_cost
                is_open = True
                reference_price = point.price

            if is_open:
                if reference_price is not None and self._should_rebalance(reference_price, point.price):
                    fee_cost = self.rebalance_fee_rate * position_notional
                    rebalance_fee_cost += fee_cost
                    equity -= fee_cost
                    reference_price = point.price
                funding_period_pnl = point.funding_rate * position_notional
                funding_pnl += funding_period_pnl
                borrow_period_cost = self.borrow_rate * position_notional
                borrow_cost += borrow_period_cost
                equity += funding_period_pnl - borrow_period_cost

            peak = max(peak, equity)
            drawdown = peak - equity
            if drawdown > max_drawdown:
                max_drawdown = drawdown
            curve.append(equity)

        if is_open and points:
            fee_cost = self.close_fee_rate * position_notional
            close_fee_cost += fee_cost
            equity -= fee_cost
            curve[-1] = equity
            peak = max(peak, equity)
            max_drawdown = max(max_drawdown, peak - equity)

        avg_liquidity = total_liquidity / Decimal(len(points)) if points else Decimal("0")
        return BacktestResult(
            total_return=equity,
            max_drawdown=max_drawdown,
            average_liquidity_usd=avg_liquidity,
            equity_curve=curve,
            funding_pnl=funding_pnl,
            open_fee_cost=open_fee_cost,
            close_fee_cost=close_fee_cost,
            rebalance_fee_cost=rebalance_fee_cost,
            borrow_cost=borrow_cost,
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

    def _should_rebalance(self, previous_price: Decimal, current_price: Decimal) -> bool:
        if self.rebalance_threshold_bps is None or previous_price == 0:
            return False
        move_bps = abs(current_price - previous_price) / previous_price * Decimal("10000")
        return move_bps >= self.rebalance_threshold_bps
