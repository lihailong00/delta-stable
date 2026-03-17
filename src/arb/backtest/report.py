"""Backtest reporting."""

from __future__ import annotations

from typing import Any

from arb.backtest.simulator import BacktestResult


def build_backtest_report(result: BacktestResult) -> dict[str, Any]:
    return {
        "total_return": str(result.total_return),
        "max_drawdown": str(result.max_drawdown),
        "average_liquidity_usd": str(result.average_liquidity_usd),
        "funding_pnl": str(result.funding_pnl),
        "open_fee_cost": str(result.open_fee_cost),
        "close_fee_cost": str(result.close_fee_cost),
        "rebalance_fee_cost": str(result.rebalance_fee_cost),
        "borrow_cost": str(result.borrow_cost),
        "trade_count": result.trade_count,
        "holding_periods": result.holding_periods,
        "capital_utilization": str(result.capital_utilization),
        "average_trade_return": str(result.average_trade_return),
        "trades": [
            {
                **trade.to_dict(),
                "opened_at": trade.opened_at.isoformat(),
                "closed_at": trade.closed_at.isoformat(),
                "funding_pnl": str(trade.funding_pnl),
                "open_fee_cost": str(trade.open_fee_cost),
                "close_fee_cost": str(trade.close_fee_cost),
                "rebalance_fee_cost": str(trade.rebalance_fee_cost),
                "borrow_cost": str(trade.borrow_cost),
                "net_pnl": str(trade.net_pnl),
            }
            for trade in result.trades
        ],
        "num_points": len(result.equity_curve),
    }
