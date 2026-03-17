"""阈值驱动回测示例：展示开仓、持有、平仓和交易账本。

运行：
PYTHONPATH=src uv run python examples/backtest_threshold_strategy.py
"""

from __future__ import annotations

import json
from decimal import Decimal

from arb.backtest.loader import load_points
from arb.backtest.report import build_backtest_report
from arb.backtest.simulator import FundingBacktester


ROWS = [
    {"ts": "2026-03-16T00:00:00+00:00", "price": "100", "funding_rate": "0.0001", "liquidity_usd": "100000"},
    {"ts": "2026-03-16T08:00:00+00:00", "price": "100", "funding_rate": "0.0007", "liquidity_usd": "100000"},
    {"ts": "2026-03-16T16:00:00+00:00", "price": "104", "funding_rate": "0.0006", "liquidity_usd": "110000"},
    {"ts": "2026-03-17T00:00:00+00:00", "price": "104", "funding_rate": "0.00005", "liquidity_usd": "90000"},
    {"ts": "2026-03-17T08:00:00+00:00", "price": "104", "funding_rate": "0.0008", "liquidity_usd": "95000"},
    {"ts": "2026-03-17T16:00:00+00:00", "price": "104", "funding_rate": "0.00005", "liquidity_usd": "95000"},
]


def main() -> None:
    points = load_points(ROWS)
    backtester = FundingBacktester(
        open_threshold=Decimal("0.0005"),
        close_threshold=Decimal("0.0001"),
        open_fee_rate=Decimal("0.0001"),
        close_fee_rate=Decimal("0.0001"),
        rebalance_fee_rate=Decimal("0.0002"),
        rebalance_threshold_bps=Decimal("300"),
        borrow_rate=Decimal("0.00005"),
    )
    result = backtester.run(points, position_notional=Decimal("1000"))
    print("threshold_strategy_example")
    print(json.dumps(build_backtest_report(result), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
