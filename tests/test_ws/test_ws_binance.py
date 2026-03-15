from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arb.models import MarketType
from arb.ws.binance import BinanceWebSocketClient


class BinanceWebSocketTests(unittest.TestCase):
    def test_builds_json_subscribe_messages(self) -> None:
        client = BinanceWebSocketClient(MarketType.SPOT)
        payload = client.build_subscribe_message("bookTicker", symbol="BTC/USDT")
        self.assertEqual(payload["method"], "SUBSCRIBE")
        self.assertEqual(payload["params"], ["btcusdt@bookTicker"])

    def test_parses_book_ticker_updates(self) -> None:
        client = BinanceWebSocketClient(MarketType.SPOT)
        events = client.parse_message(
            {
                "s": "BTCUSDT",
                "b": "25.35190000",
                "B": "31.21000000",
                "a": "25.36520000",
                "A": "40.66000000",
            }
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].channel, "orderbook.ticker")
        self.assertEqual(events[0].payload["symbol"], "BTC/USDT")
        self.assertEqual(events[0].payload["best_bid"], Decimal("25.35190000"))

    def test_parses_depth_updates(self) -> None:
        client = BinanceWebSocketClient(MarketType.SPOT)
        events = client.parse_message(
            {
                "e": "depthUpdate",
                "s": "BNBUSDT",
                "U": 157,
                "u": 160,
                "b": [["0.0024", "10"]],
                "a": [["0.0026", "100"]],
            }
        )
        self.assertEqual(events[0].channel, "orderbook.update")
        self.assertEqual(events[0].payload["symbol"], "BNB/USDT")

    def test_parses_mark_price_updates(self) -> None:
        client = BinanceWebSocketClient(MarketType.PERPETUAL)
        events = client.parse_message(
            {
                "e": "markPriceUpdate",
                "s": "BTCUSDT",
                "p": "11794.15000000",
                "i": "11784.62659091",
                "r": "0.00038167",
                "T": 1562306400000,
            }
        )
        self.assertEqual(events[0].channel, "funding.update")
        self.assertEqual(events[0].payload["funding_rate"], Decimal("0.00038167"))


if __name__ == "__main__":
    unittest.main()
