from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arb.models import MarketType
from arb.ws.bybit import BybitWebSocketClient


class BybitWebSocketTests(unittest.TestCase):
    def test_builds_subscribe_message(self) -> None:
        client = BybitWebSocketClient(MarketType.SPOT)
        payload = client.build_subscribe_message("orderbook", symbol="BTC/USDT")
        self.assertEqual(payload["op"], "subscribe")
        self.assertEqual(payload["args"], ["orderbook.50.BTCUSDT"])

    def test_builds_auth_message(self) -> None:
        client = BybitWebSocketClient(MarketType.PERPETUAL, api_key="key", api_secret="secret", private=True)
        payload = client.build_auth_message(1662350400000)
        self.assertEqual(payload["op"], "auth")
        self.assertEqual(payload["args"][0], "key")
        self.assertTrue(payload["args"][2])

    def test_parses_orderbook_messages(self) -> None:
        client = BybitWebSocketClient(MarketType.SPOT)
        events = client.parse_message(
            {
                "topic": "orderbook.50.BTCUSDT",
                "type": "snapshot",
                "data": {
                    "s": "BTCUSDT",
                    "b": [["16493.50", "0.006"]],
                    "a": [["16611.00", "0.029"]],
                    "u": 18521288,
                },
            }
        )
        self.assertEqual(events[0].channel, "orderbook.update")
        self.assertEqual(events[0].payload["symbol"], "BTC/USDT")

    def test_parses_ticker_messages(self) -> None:
        client = BybitWebSocketClient(MarketType.PERPETUAL)
        events = client.parse_message(
            {
                "topic": "tickers.BTCUSDT",
                "data": {
                    "symbol": "BTCUSDT",
                    "bid1Price": "100",
                    "ask1Price": "101",
                    "lastPrice": "100.5",
                    "fundingRate": "0.0001",
                },
            }
        )
        self.assertEqual(events[0].channel, "ticker.update")
        self.assertEqual(events[0].payload["last"], Decimal("100.5"))
        self.assertEqual(events[0].payload["funding_rate"], Decimal("0.0001"))


if __name__ == "__main__":
    unittest.main()
