"""离线示例：加载真实 Binance 历史数据并生成阈值驱动回测报告。

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
CONFIG = {
    "position_notional": Decimal("10000"),
    "open_threshold": Decimal("0.00003"),
    "close_threshold": Decimal("0.00001"),
    "open_fee_rate": Decimal("0.00002"),
    "close_fee_rate": Decimal("0.00002"),
    "borrow_rate": Decimal("0.000005"),
    "rebalance_fee_rate": Decimal("0.00001"),
    "rebalance_threshold_bps": Decimal("100"),
}


def main() -> None:
    with DATASET_PATH.open("r", encoding="utf-8", newline="") as handle:
        points = load_points(list(csv.DictReader(handle)))
    backtester = FundingBacktester(
        open_threshold=CONFIG["open_threshold"],
        close_threshold=CONFIG["close_threshold"],
        open_fee_rate=CONFIG["open_fee_rate"],
        close_fee_rate=CONFIG["close_fee_rate"],
        borrow_rate=CONFIG["borrow_rate"],
        rebalance_fee_rate=CONFIG["rebalance_fee_rate"],
        rebalance_threshold_bps=CONFIG["rebalance_threshold_bps"],
    )
    result = backtester.run(points, position_notional=CONFIG["position_notional"])
    print(f"dataset={DATASET_PATH}")
    print(f"funding_source={FUNDING_SOURCE}")
    print(f"kline_source={KLINE_SOURCE}")
    print(
        "config="
        + json.dumps(
            {key: str(value) for key, value in CONFIG.items()},
            indent=2,
            ensure_ascii=False,
        )
    )
    print(json.dumps(build_backtest_report(result), indent=2))


if __name__ == "__main__":
    main()
