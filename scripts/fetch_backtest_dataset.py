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

import sys
from pathlib import Path
from typing import Annotated

import typer

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from arb.backtest.dataset_fetcher import (  # noqa: E402
    BinancePublicDataFetcher,
    default_output_path,
    write_dataset_csv,
)
from arb.cli_support import normalize_multi_value_options  # noqa: E402

_OPTION_NAMES = {
    "--symbol",
    "--start",
    "--end",
    "--interval-hours",
    "--output-dir",
    "--combined-output",
    "--strict",
    "--help",
}
_MULTI_VALUE_OPTIONS = {
    "--symbol",
}

def main(
    symbol: Annotated[list[str], typer.Option("--symbol", help="Binance futures symbols such as BTCUSDT ETHUSDT")],
    start: Annotated[str, typer.Option("--start", help="Start month in YYYY-MM")],
    end: Annotated[str, typer.Option("--end", help="End month in YYYY-MM")],
    interval_hours: Annotated[int, typer.Option("--interval-hours", help="Funding and kline interval in hours, for example 1, 2, 4, 8")] = 8,
    output_dir: Annotated[Path, typer.Option("--output-dir", help="Directory for per-symbol output CSV files")] = Path("data/backtest/binance"),
    combined_output: Annotated[Path | None, typer.Option("--combined-output", help="Optional CSV path for a merged multi-symbol dataset")] = None,
    strict: Annotated[bool, typer.Option("--strict", help="Fail immediately when a monthly archive is missing")] = False,
) -> None:
    fetcher = BinancePublicDataFetcher()
    results = fetcher.fetch_many(
        symbol,
        start,
        end,
        interval_hours=interval_hours,
        strict=strict,
    )

    combined_rows: list[dict[str, str]] = []
    for result in results:
        output_path = default_output_path(
            output_dir,
            result.symbol,
            start,
            end,
            interval_hours=interval_hours,
        )
        write_dataset_csv(output_path, result.rows)
        combined_rows.extend(result.rows)
        print(
            f"{result.symbol}: rows={len(result.rows)} output={output_path}",
            f"missing_months={','.join(result.missing_months) or 'none'}",
        )

    if combined_output:
        combined_rows.sort(key=lambda item: (item["symbol"], item["ts"]))
        combined_path = write_dataset_csv(combined_output, combined_rows)
        print(f"combined: rows={len(combined_rows)} output={combined_path}")


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
