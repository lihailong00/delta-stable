"""Fetch and merge Binance public funding datasets for backtesting."""

from __future__ import annotations

import csv
import io
import zipfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

EIGHT_HOURS_MS = 8 * 60 * 60 * 1000
DEFAULT_TIMEOUT = 20.0
CSV_FIELDNAMES = (
    "exchange",
    "symbol",
    "ts",
    "price",
    "funding_rate",
    "liquidity_usd",
    "source_month",
)

Opener = Callable[..., Any]


class DatasetFetchError(RuntimeError):
    """Raised when a public dataset cannot be fetched or parsed."""


class DatasetNotFoundError(DatasetFetchError):
    """Raised when a monthly dataset file is not available."""


@dataclass(slots=True, frozen=True)
class MonthlySourceUrls:
    funding_url: str
    kline_url: str


@dataclass(slots=True, frozen=True)
class SymbolDataset:
    symbol: str
    rows: list[dict[str, str]]
    missing_months: list[str]


def normalize_month(month: str) -> tuple[int, int]:
    """将 YYYY-MM 字符串解析为年、月整数元组。"""

    try:
        year_str, month_str = month.split("-", 1)
        year = int(year_str)
        month_number = int(month_str)
    except Exception as exc:
        raise ValueError(f"invalid month format: {month}") from exc
    if month_number < 1 or month_number > 12:
        raise ValueError(f"invalid month format: {month}")
    return year, month_number


def iter_months(start_month: str, end_month: str) -> list[str]:
    """按月生成闭区间内的所有 YYYY-MM 字符串。"""

    # 先校验并标准化起止月份。
    start = normalize_month(start_month)
    end = normalize_month(end_month)
    if start > end:
        raise ValueError("start month must be earlier than or equal to end month")

    year, month_number = start
    months: list[str] = []
    # 逐月推进，直到覆盖结束月份。
    while (year, month_number) <= end:
        months.append(f"{year:04d}-{month_number:02d}")
        month_number += 1
        if month_number > 12:
            year += 1
            month_number = 1
    return months


def floor_to_interval_ms(timestamp_ms: int, *, interval_ms: int = EIGHT_HOURS_MS) -> int:
    """将毫秒时间戳向下对齐到指定间隔边界。"""

    return (timestamp_ms // interval_ms) * interval_ms


def build_monthly_source_urls(symbol: str, month: str) -> MonthlySourceUrls:
    """构造指定交易对和月份对应的 Binance 月度数据地址。"""

    normalized_symbol = symbol.upper()
    return MonthlySourceUrls(
        funding_url=(
            "https://data.binance.vision/data/futures/um/monthly/fundingRate/"
            f"{normalized_symbol}/{normalized_symbol}-fundingRate-{month}.zip"
        ),
        kline_url=(
            "https://data.binance.vision/data/futures/um/monthly/klines/"
            f"{normalized_symbol}/8h/{normalized_symbol}-8h-{month}.zip"
        ),
    )


def merge_month_rows(
    symbol: str,
    month: str,
    funding_rows: Iterable[dict[str, str]],
    kline_rows: Iterable[dict[str, str]],
) -> list[dict[str, str]]:
    """按 8 小时时间桶合并资金费率和 K 线数据。"""

    funding_by_bucket: dict[int, str] = {}
    # 先把资金费率按时间桶索引，便于后续快速关联。
    for row in funding_rows:
        bucket = floor_to_interval_ms(int(row["calc_time"]))
        funding_by_bucket[bucket] = str(row["last_funding_rate"])

    merged: list[dict[str, str]] = []
    # 遍历 K 线时间桶，只保留能匹配到资金费率的记录。
    for row in kline_rows:
        bucket = floor_to_interval_ms(int(row["open_time"]))
        funding_rate = funding_by_bucket.get(bucket)
        if funding_rate is None:
            continue
        merged.append(
            {
                "exchange": "binance",
                "symbol": symbol.upper(),
                "ts": datetime.fromtimestamp(bucket / 1000, tz=timezone.utc).isoformat(),
                "price": str(row["close"]),
                "funding_rate": funding_rate,
                "liquidity_usd": str(row.get("quote_volume", "0")),
                "source_month": month,
            }
        )
    # 输出前按时间排序，保证回测输入稳定。
    merged.sort(key=lambda item: item["ts"])
    return merged


def default_output_path(output_dir: str | Path, symbol: str, start_month: str, end_month: str) -> Path:
    """生成默认的数据集输出文件路径。"""

    safe_start = start_month.replace("-", "_")
    safe_end = end_month.replace("-", "_")
    return Path(output_dir) / f"binance_{symbol.lower()}_{safe_start}_{safe_end}.csv"


def write_dataset_csv(path: str | Path, rows: Iterable[dict[str, str]]) -> Path:
    """将数据集记录写入标准 CSV 文件。"""

    target = Path(path)
    # 先确保输出目录存在，再一次性写入表头和数据。
    target.parent.mkdir(parents=True, exist_ok=True)
    materialized_rows = list(rows)
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        writer.writerows(materialized_rows)
    return target


class BinancePublicDataFetcher:
    """Download and align Binance funding rate and futures kline archives."""

    def __init__(
        self,
        *,
        opener: Opener | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        """初始化公共数据抓取器，并允许注入自定义请求实现。"""

        self.opener = opener or urlopen
        self.timeout = timeout

    def fetch_symbol(
        self,
        symbol: str,
        start_month: str,
        end_month: str,
        *,
        strict: bool = False,
    ) -> SymbolDataset:
        """抓取单个交易对在指定月份区间内的回测数据。"""

        rows: list[dict[str, str]] = []
        missing_months: list[str] = []
        # 逐月抓取资金费率和 K 线，并在本地完成合并。
        for month in iter_months(start_month, end_month):
            urls = build_monthly_source_urls(symbol, month)
            try:
                funding_rows = self._read_zipped_csv(urls.funding_url)
                kline_rows = self._read_zipped_csv(urls.kline_url)
            except DatasetNotFoundError:
                # 非严格模式下记录缺失月份，继续处理后续月份。
                if strict:
                    raise
                missing_months.append(month)
                continue
            rows.extend(merge_month_rows(symbol, month, funding_rows, kline_rows))
        # 最终结果再次全局排序，便于直接用于回测。
        rows.sort(key=lambda item: item["ts"])
        return SymbolDataset(symbol=symbol.upper(), rows=rows, missing_months=missing_months)

    def fetch_many(
        self,
        symbols: Iterable[str],
        start_month: str,
        end_month: str,
        *,
        strict: bool = False,
    ) -> list[SymbolDataset]:
        """批量抓取多个交易对的数据集。"""

        return [
            self.fetch_symbol(symbol, start_month, end_month, strict=strict)
            for symbol in symbols
        ]

    def _read_zipped_csv(self, url: str) -> list[dict[str, str]]:
        """下载 ZIP 压缩包并解析其中的首个 CSV 文件。"""

        request = Request(url, headers={"User-Agent": "delta-stable/0.1"})
        try:
            # 先发起 HTTP 请求并读取压缩包字节内容。
            with self.opener(request, timeout=self.timeout) as response:
                payload = response.read()
        except HTTPError as exc:
            if exc.code == 404:
                raise DatasetNotFoundError(url) from exc
            raise DatasetFetchError(f"request failed: {url} status={exc.code}") from exc
        except URLError as exc:
            raise DatasetFetchError(f"request failed: {url} reason={exc.reason}") from exc
        except Exception as exc:
            raise DatasetFetchError(f"request failed: {url} error={exc}") from exc

        try:
            # 解压 ZIP 后读取首个 CSV，并按字典行返回。
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                csv_names = [name for name in archive.namelist() if name.endswith(".csv")]
                if not csv_names:
                    raise DatasetFetchError(f"archive has no csv payload: {url}")
                with archive.open(csv_names[0]) as handle:
                    text = handle.read().decode("utf-8-sig")
        except zipfile.BadZipFile as exc:
            raise DatasetFetchError(f"invalid zip payload: {url}") from exc

        return list(csv.DictReader(io.StringIO(text)))
