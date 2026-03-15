"""Backtest reporting."""

from __future__ import annotations

from typing import Any

from arb.backtest.simulator import BacktestResult


def build_backtest_report(result: BacktestResult) -> dict[str, Any]:
    return {
        "total_return": str(result.total_return),
        "max_drawdown": str(result.max_drawdown),
        "average_liquidity_usd": str(result.average_liquidity_usd),
        "num_points": len(result.equity_curve),
    }
