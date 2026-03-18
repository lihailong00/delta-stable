from __future__ import annotations

import csv
import io
import sys
import zipfile
from pathlib import Path
from urllib.error import HTTPError

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from arb.backtest.dataset_fetcher import (
    BinancePublicDataFetcher,
    DatasetFetchError,
    DatasetNotFoundError,
    build_monthly_source_urls,
    default_output_path,
    interval_to_label,
    iter_months,
    merge_month_rows,
    write_dataset_csv,
)


def _zip_csv(filename: str, rows: list[dict[str, str]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        text_buffer = io.StringIO()
        writer = csv.DictWriter(text_buffer, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
        archive.writestr(filename, text_buffer.getvalue())
    return buffer.getvalue()


class _Response:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return self.payload

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class _Opener:
    def __init__(self, mapping: dict[str, bytes]) -> None:
        self.mapping = mapping

    def __call__(self, request, timeout=None) -> _Response:
        url = request.full_url
        if url not in self.mapping:
            raise HTTPError(url, 404, "not found", hdrs=None, fp=None)
        return _Response(self.mapping[url])


class TestDatasetFetcher:

    def test_iter_months_is_inclusive(self) -> None:
        assert iter_months('2026-01', '2026-03') == ['2026-01', '2026-02', '2026-03']

    def test_merge_month_rows_aligns_by_configured_interval_bucket(self) -> None:
        merged = merge_month_rows(
            'BTCUSDT',
            '2026-02',
            [{'calc_time': '1769904000001', 'funding_interval_hours': '4', 'last_funding_rate': '-0.00003267'}],
            [{'open_time': '1769904000000', 'close': '78320.80', 'quote_volume': '2981356447.19'}],
            interval_hours=4,
        )
        assert merged == [
            {
                'exchange': 'binance',
                'symbol': 'BTCUSDT',
                'ts': '2026-02-01T00:00:00+00:00',
                'price': '78320.80',
                'funding_rate': '-0.00003267',
                'funding_interval_hours': '4',
                'liquidity_usd': '2981356447.19',
                'source_month': '2026-02',
            }
        ]

    def test_fetch_symbol_skips_missing_months_when_not_strict(self) -> None:
        funding_rows = [
            {'calc_time': '1769904000001', 'funding_interval_hours': '8', 'last_funding_rate': '-0.00003267'}
        ]
        kline_rows = [
            {
                'open_time': '1769904000000',
                'open': '78706.70',
                'high': '79396.80',
                'low': '77899.90',
                'close': '78320.80',
                'volume': '37907.193',
                'close_time': '1769932799999',
                'quote_volume': '2981356447.19170',
                'count': '1475094',
                'taker_buy_volume': '18418.904',
                'taker_buy_quote_volume': '1449009303.36000',
                'ignore': '0',
            }
        ]
        opener = _Opener(
            {
                'https://data.binance.vision/data/futures/um/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-2026-01.zip': _zip_csv(
                    'BTCUSDT-fundingRate-2026-01.csv',
                    funding_rows,
                ),
                'https://data.binance.vision/data/futures/um/monthly/klines/BTCUSDT/4h/BTCUSDT-4h-2026-01.zip': _zip_csv(
                    'BTCUSDT-4h-2026-01.csv',
                    kline_rows,
                ),
            }
        )

        fetcher = BinancePublicDataFetcher(opener=opener)
        result = fetcher.fetch_symbol('BTCUSDT', '2026-01', '2026-02', interval_hours=4)

        assert len(result.rows) == 1
        assert result.rows[0]['symbol'] == 'BTCUSDT'
        assert result.rows[0]['funding_interval_hours'] == '8'
        assert result.missing_months == ['2026-02']

    def test_fetch_symbol_raises_on_missing_month_in_strict_mode(self) -> None:
        fetcher = BinancePublicDataFetcher(opener=_Opener({}))
        with pytest.raises(DatasetNotFoundError):
            fetcher.fetch_symbol('BTCUSDT', '2026-01', '2026-01', strict=True)

    def test_write_dataset_csv_persists_backtest_shape(self, tmp_path: Path) -> None:
        path = default_output_path(tmp_path, 'BTCUSDT', '2026-01', '2026-02', interval_hours=4)
        write_dataset_csv(
            path,
            [
                {
                    'exchange': 'binance',
                    'symbol': 'BTCUSDT',
                    'ts': '2026-02-01T00:00:00+00:00',
                    'price': '78320.80',
                    'funding_rate': '-0.00003267',
                    'funding_interval_hours': '4',
                    'liquidity_usd': '2981356447.19170',
                    'source_month': '2026-02',
                }
            ],
        )
        rows = list(csv.DictReader(path.open('r', encoding='utf-8', newline='')))
        assert rows[0]['ts'] == '2026-02-01T00:00:00+00:00'
        assert rows[0]['funding_rate'] == '-0.00003267'
        assert rows[0]['funding_interval_hours'] == '4'
        assert path.name.endswith('4h_2026_01_2026_02.csv')

    def test_interval_label_formats_supported_hours(self) -> None:
        assert interval_to_label(1) == '1h'
        assert interval_to_label(8) == '8h'

    def test_merge_month_rows_sorts_out_of_order_inputs_and_skips_unmatched_bucket(self) -> None:
        merged = merge_month_rows(
            'ETHUSDT',
            '2026-02',
            [
                # 故意把较晚的 funding 放前面，验证函数会在输出前重新按时间排序。
                {'calc_time': '1769911200001', 'funding_interval_hours': '1', 'last_funding_rate': '0.00030000'},
                {'calc_time': '1769907600001', 'funding_interval_hours': '1', 'last_funding_rate': '0.00010000'},
            ],
            [
                # 这里把 K 线也打乱顺序，同时插入一个没有 funding 的时间桶。
                {'open_time': '1769914800000', 'close': '2815.20', 'quote_volume': '3200000.5'},
                {'open_time': '1769911200000', 'close': '2808.40', 'quote_volume': '2800000.2'},
                {'open_time': '1769907600000', 'close': '2798.10', 'quote_volume': '3000000.1'},
            ],
            interval_hours=1,
        )

        # 02:00 这个时间桶没有 funding，应该被过滤掉，只保留两个可匹配的时间桶。
        assert len(merged) == 2
        assert [row['funding_rate'] for row in merged] == ['0.00010000', '0.00030000']
        assert [row['price'] for row in merged] == ['2798.10', '2808.40']

    def test_merge_month_rows_uses_requested_interval_when_funding_interval_missing(self) -> None:
        merged = merge_month_rows(
            'BTCUSDT',
            '2026-02',
            [
                # 模拟旧数据里没有 funding_interval_hours 字段，应该回退到调用方传入的周期。
                {'calc_time': '1769904000001', 'last_funding_rate': '-0.00003267'},
            ],
            [
                {'open_time': '1769904000000', 'close': '78320.80', 'quote_volume': '2981356447.19'},
            ],
            interval_hours=4,
        )

        assert merged[0]['funding_interval_hours'] == '4'

    def test_merge_month_rows_uses_explicit_exchange_in_output(self) -> None:
        merged = merge_month_rows(
            'BTCUSDT',
            '2026-02',
            [
                # 这里显式传入 gate，验证统一回测格式里的 exchange 不再被写死为 binance。
                {'calc_time': '1769904000001', 'funding_interval_hours': '4', 'last_funding_rate': '0.00012000'},
            ],
            [
                {'open_time': '1769904000000', 'close': '78320.80', 'quote_volume': '2981356447.19'},
            ],
            exchange='gate',
            interval_hours=4,
        )

        assert merged[0]['exchange'] == 'gate'

    def test_fetch_many_keeps_symbol_results_isolated_when_missing_months_differ(self) -> None:
        funding_rows_jan = [
            {'calc_time': '1769904000001', 'funding_interval_hours': '4', 'last_funding_rate': '-0.00003267'}
        ]
        kline_rows_jan = [
            {'open_time': '1769904000000', 'close': '78320.80', 'quote_volume': '2981356447.19'}
        ]
        funding_rows_feb = [
            {'calc_time': '1770249600001', 'funding_interval_hours': '4', 'last_funding_rate': '0.00011890'}
        ]
        kline_rows_feb = [
            {'open_time': '1770249600000', 'close': '2935.10', 'quote_volume': '1686356447.19'}
        ]
        opener = _Opener(
            {
                # BTC 只提供 1 月数据，2 月缺失。
                'https://data.binance.vision/data/futures/um/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-2026-01.zip': _zip_csv(
                    'BTCUSDT-fundingRate-2026-01.csv',
                    funding_rows_jan,
                ),
                'https://data.binance.vision/data/futures/um/monthly/klines/BTCUSDT/4h/BTCUSDT-4h-2026-01.zip': _zip_csv(
                    'BTCUSDT-4h-2026-01.csv',
                    kline_rows_jan,
                ),
                # ETH 只提供 2 月数据，1 月缺失。
                'https://data.binance.vision/data/futures/um/monthly/fundingRate/ETHUSDT/ETHUSDT-fundingRate-2026-02.zip': _zip_csv(
                    'ETHUSDT-fundingRate-2026-02.csv',
                    funding_rows_feb,
                ),
                'https://data.binance.vision/data/futures/um/monthly/klines/ETHUSDT/4h/ETHUSDT-4h-2026-02.zip': _zip_csv(
                    'ETHUSDT-4h-2026-02.csv',
                    kline_rows_feb,
                ),
            }
        )

        fetcher = BinancePublicDataFetcher(opener=opener)
        datasets = fetcher.fetch_many(['BTCUSDT', 'ETHUSDT'], '2026-01', '2026-02', interval_hours=4)

        # 这里验证批量抓取时，每个 symbol 的缺失月份和结果行都独立维护，不会串数据。
        assert [dataset.symbol for dataset in datasets] == ['BTCUSDT', 'ETHUSDT']
        assert datasets[0].missing_months == ['2026-02']
        assert datasets[1].missing_months == ['2026-01']
        assert [row['symbol'] for row in datasets[0].rows] == ['BTCUSDT']
        assert [row['symbol'] for row in datasets[1].rows] == ['ETHUSDT']
        assert datasets[0].rows[0]['funding_rate'] == '-0.00003267'
        assert datasets[1].rows[0]['funding_rate'] == '0.00011890'

    def test_fetch_symbol_raises_dataset_fetch_error_for_invalid_zip_payload(self) -> None:
        opener = _Opener(
            {
                # 模拟远端返回了非 ZIP 内容，验证错误路径不会被吞掉。
                'https://data.binance.vision/data/futures/um/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-2026-01.zip': b'not-a-zip',
                'https://data.binance.vision/data/futures/um/monthly/klines/BTCUSDT/8h/BTCUSDT-8h-2026-01.zip': b'not-a-zip',
            }
        )

        fetcher = BinancePublicDataFetcher(opener=opener)
        with pytest.raises(DatasetFetchError, match='invalid zip payload'):
            fetcher.fetch_symbol('BTCUSDT', '2026-01', '2026-01', interval_hours=8, strict=True)

    def test_build_monthly_source_urls_and_output_path_follow_interval_hours(self, tmp_path: Path) -> None:
        # 这里验证非默认周期会同时反映到下载 URL 和本地输出文件名。
        urls = build_monthly_source_urls('BTCUSDT', '2026-02', interval_hours=2)
        output = default_output_path(tmp_path, 'BTCUSDT', '2026-01', '2026-02', interval_hours=2)

        assert urls.kline_url.endswith('/BTCUSDT/2h/BTCUSDT-2h-2026-02.zip')
        assert urls.funding_url.endswith('/BTCUSDT/BTCUSDT-fundingRate-2026-02.zip')
        assert output.name == 'binance_btcusdt_2h_2026_01_2026_02.csv'
