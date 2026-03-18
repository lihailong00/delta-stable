"""Backtest helpers."""

from .dataset_fetcher import (
    BinancePublicDataFetcher,
    DatasetFetchError,
    DatasetNotFoundError,
    build_monthly_source_urls,
    default_output_path,
    iter_months,
    merge_month_rows,
    write_dataset_csv,
)
from .loader import load_points
from .report import build_backtest_report
from .schemas import BacktestReport, BacktestResult, BacktestTrade, HistoricalPoint, SymbolDataset
from .simulator import FundingBacktester

__all__ = [
    "BacktestReport",
    "BacktestResult",
    "BacktestTrade",
    "BinancePublicDataFetcher",
    "DatasetFetchError",
    "DatasetNotFoundError",
    "FundingBacktester",
    "HistoricalPoint",
    "SymbolDataset",
    "build_backtest_report",
    "build_monthly_source_urls",
    "default_output_path",
    "iter_months",
    "load_points",
    "merge_month_rows",
    "write_dataset_csv",
]
