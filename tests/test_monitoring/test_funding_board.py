from __future__ import annotations

import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arb.monitoring.funding_board import FundingBoard
from arb.scanner.funding_scanner import FundingScanner


def _snapshot(exchange: str, symbol: str, rate: str, liquidity: str, *, funding_interval_hours: int = 8) -> dict[str, object]:
    ts = datetime(2026, 3, 17, tzinfo=timezone.utc).isoformat()
    return {
        "ticker": {
            "exchange": exchange,
            "symbol": symbol,
            "market_type": "perpetual",
            "bid": "100.0",
            "ask": "100.2",
            "last": "100.1",
            "ts": ts,
        },
        "funding": {
            "exchange": exchange,
            "symbol": symbol,
            "rate": rate,
            "predicted_rate": rate,
            "funding_interval_hours": funding_interval_hours,
            "next_funding_time": datetime(2026, 3, 17, 8, tzinfo=timezone.utc).isoformat(),
            "ts": ts,
        },
        "liquidity_usd": liquidity,
    }


class TestFundingBoard:
    def test_build_rows_sorts_by_net_rate(self) -> None:
        board = FundingBoard(scanner=FundingScanner(min_net_rate=Decimal("0.0001")), top_n=2)

        rows = board.build_rows(
            [
                _snapshot("binance", "BTC/USDT", "0.001", "1000000"),
                _snapshot("okx", "ETH/USDT", "0.0005", "900000"),
            ]
        )

        assert [row.symbol for row in rows] == ["BTC/USDT", "ETH/USDT"]
        assert rows[0].next_funding_time is not None
        assert rows[0].funding_interval_hours == 8

    def test_build_rows_filters_low_liquidity(self) -> None:
        board = FundingBoard(
            scanner=FundingScanner(min_net_rate=Decimal("0")),
            min_liquidity_usd=Decimal("500000"),
        )

        rows = board.build_rows(
            [
                _snapshot("binance", "BTC/USDT", "0.001", "1000000"),
                _snapshot("binance", "DOGE/USDT", "0.002", "1000"),
            ]
        )

        assert len(rows) == 1
        assert rows[0].symbol == "BTC/USDT"
