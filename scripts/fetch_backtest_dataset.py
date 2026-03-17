#!/usr/bin/env python3
"""Fetch Binance public futures datasets for funding backtests.

Examples:
PYTHONPATH=src uv run python scripts/fetch_backtest_dataset.py \
  --symbol BTCUSDT ETHUSDT \
  --start 2024-01 \
  --end 2026-02 \
  --output-dir data/backtest/binance \
  --combined-output data/backtest/binance/combined_2024_01_2026_02.csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from arb.backtest.dataset_fetcher import (  # noqa: E402
    BinancePublicDataFetcher,
    default_output_path,
    write_dataset_csv,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fetch_backtest_dataset")
    parser.add_argument("--symbol", nargs="+", required=True, help="Binance futures symbols such as BTCUSDT ETHUSDT")
    parser.add_argument("--start", required=True, help="Start month in YYYY-MM")
    parser.add_argument("--end", required=True, help="End month in YYYY-MM")
    parser.add_argument(
        "--interval-hours",
        type=int,
        default=8,
        help="Funding and kline interval in hours, for example 1, 2, 4, 8",
    )
    parser.add_argument(
        "--output-dir",
        default="data/backtest/binance",
        help="Directory for per-symbol output CSV files",
    )
    parser.add_argument(
        "--combined-output",
        help="Optional CSV path for a merged multi-symbol dataset",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail immediately when a monthly archive is missing",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    fetcher = BinancePublicDataFetcher()
    results = fetcher.fetch_many(
        args.symbol,
        args.start,
        args.end,
        interval_hours=args.interval_hours,
        strict=args.strict,
    )

    combined_rows: list[dict[str, str]] = []
    for result in results:
        output_path = default_output_path(
            args.output_dir,
            result.symbol,
            args.start,
            args.end,
            interval_hours=args.interval_hours,
        )
        write_dataset_csv(output_path, result.rows)
        combined_rows.extend(result.rows)
        print(
            f"{result.symbol}: rows={len(result.rows)} output={output_path}",
            f"missing_months={','.join(result.missing_months) or 'none'}",
        )

    if args.combined_output:
        combined_rows.sort(key=lambda item: (item["symbol"], item["ts"]))
        combined_path = write_dataset_csv(args.combined_output, combined_rows)
        print(f"combined: rows={len(combined_rows)} output={combined_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
