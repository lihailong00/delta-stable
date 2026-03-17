from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arb.market.spot_perp_view import SpotPerpQuoteView, build_spot_perp_view


class TestSpotPerpView:
    def test_basis_bps_and_sync_window(self) -> None:
        view = SpotPerpQuoteView(
            exchange="binance",
            symbol="BTC/USDT",
            spot_ticker={
                "exchange": "binance",
                "symbol": "BTC/USDT",
                "bid": "100",
                "ask": "101",
                "last": "100.5",
                "ts": "2026-03-17T00:00:00+00:00",
            },
            perp_ticker={
                "exchange": "binance",
                "symbol": "BTC/USDT",
                "bid": "100.3",
                "ask": "100.5",
                "last": "100.4",
                "ts": "2026-03-17T00:00:02+00:00",
            },
            funding={
                "exchange": "binance",
                "symbol": "BTC/USDT",
                "rate": "0.001",
                "ts": "2026-03-17T00:00:02+00:00",
            },
        )
        assert view.synchronized_within(3)
        assert view.basis_bps() == Decimal("-69.30693069306930693069306931")

    def test_build_spot_perp_view_marks_unsynchronized_payload(self) -> None:
        payload = build_spot_perp_view(
            exchange="binance",
            symbol="BTC/USDT",
            spot_ticker={
                "exchange": "binance",
                "symbol": "BTC/USDT",
                "bid": "100",
                "ask": "101",
                "last": "100.5",
                "ts": "2026-03-17T00:00:00+00:00",
            },
            perp_ticker={
                "exchange": "binance",
                "symbol": "BTC/USDT",
                "bid": "100.3",
                "ask": "100.5",
                "last": "100.4",
                "ts": "2026-03-17T00:00:10+00:00",
            },
            funding={
                "exchange": "binance",
                "symbol": "BTC/USDT",
                "rate": "0.001",
                "ts": "2026-03-17T00:00:10+00:00",
            },
            max_age_seconds=3,
        )
        assert not payload["synchronized"]
        assert payload["kind"] == "spot_perp_view"
