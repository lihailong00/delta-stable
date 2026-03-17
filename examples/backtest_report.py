"""离线示例：加载真实 Binance 历史数据并生成回测报告。

运行：
PYTHONPATH=src uv run python examples/backtest_report.py
"""

from __future__ import annotations

import csv
import json
from decimal import Decimal
from pathlib import Path

from arb.backtest.loader import load_points
from arb.backtest.report import build_backtest_report
from arb.backtest.simulator import FundingBacktester


DATASET_PATH = Path(__file__).with_name("data") / "binance_btcusdt_2026_02_sample.csv"
FUNDING_SOURCE = (
    "https://data.binance.vision/data/futures/um/monthly/fundingRate/BTCUSDT/"
    "BTCUSDT-fundingRate-2026-02.zip"
)
KLINE_SOURCE = (
    "https://data.binance.vision/data/futures/um/monthly/klines/BTCUSDT/8h/"
    "BTCUSDT-8h-2026-02.zip"
)


def main() -> None:
    with DATASET_PATH.open("r", encoding="utf-8", newline="") as handle:
        points = load_points(list(csv.DictReader(handle)))
    backtester = FundingBacktester(
        fee_rate=Decimal("0.0001"),
        borrow_rate=Decimal("0.00005"),
    )
    result = backtester.run(points, position_notional=Decimal("10000"))
    print(f"dataset={DATASET_PATH}")
    print(f"funding_source={FUNDING_SOURCE}")
    print(f"kline_source={KLINE_SOURCE}")
    print(json.dumps(build_backtest_report(result), indent=2))


if __name__ == "__main__":
    main()
