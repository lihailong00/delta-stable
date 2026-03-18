"""Fetch and merge Binance public funding datasets for backtesting."""

from __future__ import annotations

import csv
import io
import zipfile
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from arb.backtest.schemas import (
    FundingCsvRow,
    KlineCsvRow,
    MergedBacktestRow,
    MonthlySourceUrls,
    SymbolDataset,
)
from arb.funding import DEFAULT_FUNDING_INTERVAL_HOURS

DEFAULT_TIMEOUT = 20.0
DEFAULT_EXCHANGE = "binance"
CSV_FIELDNAMES = (
    "exchange",
    "symbol",
    "ts",
    "price",
    "funding_rate",
    "funding_interval_hours",
    "liquidity_usd",
    "source_month",
)

class SupportsRead(Protocol):
    def read(self) -> bytes: ...

    def __enter__(self) -> "SupportsRead": ...

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None: ...


class UrlOpener(Protocol):
    def __call__(self, request: Request, timeout: float) -> SupportsRead: ...


class DatasetFetchError(RuntimeError):
    """Raised when a public dataset cannot be fetched or parsed."""


class DatasetNotFoundError(DatasetFetchError):
    """Raised when a monthly dataset file is not available."""


def normalize_month(month: str) -> tuple[int, int]:
    """将 YYYY-MM 字符串解析为年、月整数元组。

    输入：
    - month: 月份字符串，格式必须是 `YYYY-MM`，例如 `2026-03`

    输出：
    - `(year, month_number)`: 二元整数元组，例如 `(2026, 3)`

    异常：
    - `ValueError`: 当输入格式非法，或月份不在 `1..12` 时抛出
    """

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
    """按月生成闭区间内的所有 YYYY-MM 字符串。

    输入：
    - start_month: 起始月份，格式 `YYYY-MM`
    - end_month: 结束月份，格式 `YYYY-MM`

    输出：
    - 月份字符串列表，包含起止月份本身，例如 `["2026-01", "2026-02", "2026-03"]`

    异常：
    - `ValueError`: 当月份格式非法，或起始月份晚于结束月份时抛出

    处理方式：
    - 先调用 `normalize_month(...)` 校验输入
    - 再逐月推进，构造闭区间月份列表
    """

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


def interval_to_milliseconds(interval_hours: int = DEFAULT_FUNDING_INTERVAL_HOURS) -> int:
    """把 funding 周期小时数转换成毫秒数。

    输入：
    - interval_hours: funding 周期，单位是小时，例如 `1`、`4`、`8`

    输出：
    - 对应的毫秒整数，例如 `8 -> 28800000`
    """

    return interval_hours * 60 * 60 * 1000


def interval_to_label(interval_hours: int = DEFAULT_FUNDING_INTERVAL_HOURS) -> str:
    """把 funding 周期小时数转换成 URL/文件名使用的标签。

    输入：
    - interval_hours: funding 周期，单位是小时

    输出：
    - 周期标签字符串，例如 `1h`、`4h`、`8h`
    """

    return f"{interval_hours}h"


def floor_to_interval_ms(
    timestamp_ms: int,
    *,
    interval_ms: int | None = None,
    interval_hours: int = DEFAULT_FUNDING_INTERVAL_HOURS,
) -> int:
    """将毫秒时间戳向下对齐到指定间隔边界。

    输入：
    - timestamp_ms: 原始毫秒时间戳
    - interval_ms: 可选的显式时间桶大小，单位毫秒；优先级高于 `interval_hours`
    - interval_hours: 当没有传 `interval_ms` 时，使用的 funding 周期小时数

    输出：
    - 向下取整后的时间桶起点毫秒值

    处理方式：
    - 先确定最终使用的桶大小
    - 再用整除方式把时间戳对齐到桶边界
    """

    normalized_interval_ms = interval_ms or interval_to_milliseconds(interval_hours)
    return (timestamp_ms // normalized_interval_ms) * normalized_interval_ms


def build_monthly_source_urls(
    symbol: str,
    month: str,
    *,
    interval_hours: int = DEFAULT_FUNDING_INTERVAL_HOURS,
) -> MonthlySourceUrls:
    """构造指定交易对、月份和 K 线周期对应的 Binance 月度数据地址。

    输入：
    - symbol: 交易对，例如 `BTCUSDT`
    - month: 月份，格式 `YYYY-MM`
    - interval_hours: K 线周期小时数，例如 `1`、`4`、`8`

    输出：
    - `MonthlySourceUrls`: 包含该月份 funding ZIP 地址和 K 线 ZIP 地址

    处理方式：
    - 把 symbol 统一转成大写
    - 用 `interval_to_label(...)` 构造 Binance 公共数据路径
    """

    normalized_symbol = symbol.upper()
    interval_label = interval_to_label(interval_hours)
    return MonthlySourceUrls(
        funding_url=(
            "https://data.binance.vision/data/futures/um/monthly/fundingRate/"
            f"{normalized_symbol}/{normalized_symbol}-fundingRate-{month}.zip"
        ),
        kline_url=(
            "https://data.binance.vision/data/futures/um/monthly/klines/"
            f"{normalized_symbol}/{interval_label}/{normalized_symbol}-{interval_label}-{month}.zip"
        ),
    )


def merge_month_rows(
    symbol: str,
    month: str,
    funding_rows: Iterable[FundingCsvRow | Mapping[str, object]],
    kline_rows: Iterable[KlineCsvRow | Mapping[str, object]],
    *,
    exchange: str = DEFAULT_EXCHANGE,
    interval_hours: int = DEFAULT_FUNDING_INTERVAL_HOURS,
) -> list[MergedBacktestRow]:
    """按指定交易所和 funding 周期合并资金费率与 K 线数据。

    输入：
    - symbol: 交易对，例如 `BTCUSDT`
    - month: 数据来源月份，格式 `YYYY-MM`
    - funding_rows: funding CSV 解出的行列表，至少要包含：
      `calc_time`、`last_funding_rate`，可选 `funding_interval_hours`
    - kline_rows: K 线 CSV 解出的行列表，至少要包含：
      `open_time`、`close`，可选 `quote_volume`
    - exchange: 输出记录里的交易所名，例如 `binance`、`gate`
    - interval_hours: 当前 K 线数据使用的周期小时数

    输出：
    - 统一格式的回测记录列表。每一行包含：
      `exchange`、`symbol`、`ts`、`price`、`funding_rate`、
      `funding_interval_hours`、`liquidity_usd`、`source_month`

    处理方式：
    - 先把 funding 行按时间桶建立索引
    - 再遍历 K 线行，用同样的时间桶规则去关联 funding
    - 只保留 funding 和 K 线都存在的时间桶
    - 最后按 `ts` 排序，保证输出稳定
    """

    funding_by_bucket: dict[int, tuple[FundingCsvRow, int]] = {}
    # 先把资金费率按时间桶索引，便于后续快速关联。
    for raw_funding_row in funding_rows:
        funding_row = (
            raw_funding_row
            if isinstance(raw_funding_row, FundingCsvRow)
            else FundingCsvRow.model_validate(raw_funding_row)
        )
        row_interval_hours = funding_row.funding_interval_hours or interval_hours
        bucket = floor_to_interval_ms(funding_row.calc_time, interval_hours=row_interval_hours)
        funding_by_bucket[bucket] = (funding_row, row_interval_hours)

    merged: list[MergedBacktestRow] = []
    # 遍历 K 线时间桶，只保留能匹配到资金费率的记录。
    for raw_kline_row in kline_rows:
        kline_row = (
            raw_kline_row
            if isinstance(raw_kline_row, KlineCsvRow)
            else KlineCsvRow.model_validate(raw_kline_row)
        )
        bucket = floor_to_interval_ms(kline_row.open_time, interval_hours=interval_hours)
        funding_point = funding_by_bucket.get(bucket)
        if funding_point is None:
            continue
        funding_row, row_interval_hours = funding_point
        merged.append(
            MergedBacktestRow(
                exchange=exchange,
                symbol=symbol.upper(),
                ts=datetime.fromtimestamp(bucket / 1000, tz=timezone.utc),
                price=kline_row.close,
                funding_rate=funding_row.last_funding_rate,
                funding_interval_hours=row_interval_hours,
                liquidity_usd=kline_row.quote_volume,
                source_month=month,
            )
        )
    # 输出前按时间排序，保证回测输入稳定。
    merged.sort(key=lambda item: item.ts)
    return merged


def default_output_path(
    output_dir: str | Path,
    symbol: str,
    start_month: str,
    end_month: str,
    *,
    interval_hours: int = DEFAULT_FUNDING_INTERVAL_HOURS,
) -> Path:
    """生成默认的数据集输出文件路径。

    输入：
    - output_dir: 输出目录
    - symbol: 交易对，例如 `BTCUSDT`
    - start_month: 起始月份，格式 `YYYY-MM`
    - end_month: 结束月份，格式 `YYYY-MM`
    - interval_hours: K 线周期小时数

    输出：
    - `Path` 对象，例如 `data/binance_btcusdt_4h_2026_01_2026_02.csv`
    """

    safe_start = start_month.replace("-", "_")
    safe_end = end_month.replace("-", "_")
    interval_label = interval_to_label(interval_hours)
    return Path(output_dir) / f"binance_{symbol.lower()}_{interval_label}_{safe_start}_{safe_end}.csv"


def write_dataset_csv(
    path: str | Path,
    rows: Iterable[MergedBacktestRow | Mapping[str, object]],
) -> Path:
    """将数据集记录写入标准 CSV 文件。

    输入：
    - path: 输出文件路径
    - rows: 统一格式的回测记录迭代器，每一行字段应符合 `CSV_FIELDNAMES`

    输出：
    - 实际写入的 `Path` 对象

    处理方式：
    - 先创建父目录
    - 再按固定表头顺序写入 CSV
    """

    target = Path(path)
    # 先确保输出目录存在，再一次性写入表头和数据。
    target.parent.mkdir(parents=True, exist_ok=True)
    materialized_rows = list(rows)
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        writer.writerows([_serialize_dataset_row(row) for row in materialized_rows])
    return target


class BinancePublicDataFetcher:
    """Download and align Binance funding rate and futures kline archives."""

    exchange_name = DEFAULT_EXCHANGE

    def __init__(
        self,
        *,
        opener: UrlOpener | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        """初始化公共数据抓取器，并允许注入自定义请求实现。

        输入：
        - opener: 可选的 HTTP 打开器，签名需兼容 `urlopen(request, timeout=...)`
        - timeout: 请求超时时间，单位秒

        输出：
        - 无返回值；初始化后会在实例上保存 `opener` 和 `timeout`
        """

        self.opener = opener or urlopen
        self.timeout = timeout

    def fetch_symbol(
        self,
        symbol: str,
        start_month: str,
        end_month: str,
        *,
        interval_hours: int = DEFAULT_FUNDING_INTERVAL_HOURS,
        strict: bool = False,
    ) -> SymbolDataset:
        """抓取单个交易对在指定月份区间内的回测数据。

        输入：
        - symbol: 交易对，例如 `BTCUSDT`
        - start_month: 起始月份，格式 `YYYY-MM`
        - end_month: 结束月份，格式 `YYYY-MM`
        - interval_hours: K 线周期小时数
        - strict: 是否严格要求每个月数据都存在

        输出：
        - `SymbolDataset`
          - `symbol`: 标准化后的大写交易对
          - `rows`: 合并后的统一回测记录
          - `missing_months`: 缺失数据的月份列表

        异常：
        - `DatasetNotFoundError`: `strict=True` 且某个月数据缺失时抛出
        - `DatasetFetchError`: 下载或解析 ZIP 时失败

        处理方式：
        - 按月遍历区间
        - 每个月分别下载 funding ZIP 和 K 线 ZIP
        - 调用 `merge_month_rows(...)` 生成统一记录
        - 最后按时间排序并打包成 `SymbolDataset`
        """

        rows: list[MergedBacktestRow] = []
        missing_months: list[str] = []
        # 逐月抓取资金费率和 K 线，并在本地完成合并。
        for month in iter_months(start_month, end_month):
            urls = build_monthly_source_urls(symbol, month, interval_hours=interval_hours)
            try:
                funding_rows = self._parse_funding_rows(self._read_zipped_csv(urls.funding_url))
                kline_rows = self._parse_kline_rows(self._read_zipped_csv(urls.kline_url))
            except DatasetNotFoundError:
                # 非严格模式下记录缺失月份，继续处理后续月份。
                if strict:
                    raise
                missing_months.append(month)
                continue
            rows.extend(
                merge_month_rows(
                    symbol,
                    month,
                    funding_rows,
                    kline_rows,
                    exchange=self.exchange_name,
                    interval_hours=interval_hours,
                )
            )
        # 最终结果再次全局排序，便于直接用于回测。
        rows.sort(key=lambda item: item.ts)
        return SymbolDataset(symbol=symbol.upper(), rows=rows, missing_months=missing_months)

    def fetch_many(
        self,
        symbols: Iterable[str],
        start_month: str,
        end_month: str,
        *,
        interval_hours: int = DEFAULT_FUNDING_INTERVAL_HOURS,
        strict: bool = False,
    ) -> list[SymbolDataset]:
        """批量抓取多个交易对的数据集。

        输入：
        - symbols: 交易对列表或任意可迭代对象，例如 `["BTCUSDT", "ETHUSDT"]`
        - start_month: 起始月份，格式 `YYYY-MM`
        - end_month: 结束月份，格式 `YYYY-MM`
        - interval_hours: K 线周期小时数
        - strict: 是否对每个交易对都启用严格缺失检查

        输出：
        - `list[SymbolDataset]`，列表顺序与 `symbols` 的输入顺序一致

        处理方式：
        - 对每个 symbol 调用一次 `fetch_symbol(...)`
        - 不做额外合并，返回逐交易对的数据集列表
        """

        return [
            self.fetch_symbol(symbol, start_month, end_month, interval_hours=interval_hours, strict=strict)
            for symbol in symbols
        ]

    def _read_zipped_csv(self, url: str) -> list[dict[str, str]]:
        """下载 ZIP 压缩包并解析其中的首个 CSV 文件。

        输入：
        - url: ZIP 文件下载地址

        输出：
        - `list[dict[str, str]]`，CSV 每一行都会被解析成一个字典，字段和值都保持字符串形式

        异常：
        - `DatasetNotFoundError`: HTTP 404
        - `DatasetFetchError`: 非 404 的 HTTP 错误、网络错误、坏 ZIP、ZIP 中无 CSV 等情况

        处理方式：
        - 先用 `opener` 下载 ZIP 字节流
        - 再解压 ZIP，读取其中第一个 `.csv`
        - 最后通过 `csv.DictReader` 转成字典行列表
        """

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

    @staticmethod
    def _parse_funding_rows(rows: Iterable[dict[str, str]]) -> list[FundingCsvRow]:
        return [FundingCsvRow.model_validate(row) for row in rows]

    @staticmethod
    def _parse_kline_rows(rows: Iterable[dict[str, str]]) -> list[KlineCsvRow]:
        return [KlineCsvRow.model_validate(row) for row in rows]


def _serialize_dataset_row(row: MergedBacktestRow | Mapping[str, object]) -> dict[str, str]:
    typed_row = row if isinstance(row, MergedBacktestRow) else MergedBacktestRow.model_validate(row)
    return {
        "exchange": typed_row.exchange,
        "symbol": typed_row.symbol,
        "ts": typed_row.ts.isoformat(),
        "price": str(typed_row.price),
        "funding_rate": str(typed_row.funding_rate),
        "funding_interval_hours": str(typed_row.funding_interval_hours),
        "liquidity_usd": str(typed_row.liquidity_usd),
        "source_month": typed_row.source_month,
    }
