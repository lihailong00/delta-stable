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
    DatasetNotFoundError,
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
