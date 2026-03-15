from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arb.models import MarketType
from arb.ws.okx import OkxWebSocketClient


class OkxWebSocketTests(unittest.TestCase):
    def test_builds_public_subscribe_message(self) -> None:
        client = OkxWebSocketClient(MarketType.SPOT)
        payload = client.build_subscribe_message("books", symbol="BTC/USDT")
        self.assertEqual(payload["op"], "subscribe")
        self.assertEqual(payload["args"][0]["instId"], "BTC-USDT")

    def test_builds_login_message(self) -> None:
        client = OkxWebSocketClient(
            MarketType.SPOT,
            api_key="key",
            api_secret="secret",
            passphrase="pass",
            private=True,
        )
        payload = client.build_login_message("1704876947")
        self.assertEqual(payload["op"], "login")
        self.assertEqual(payload["args"][0]["apiKey"], "key")
        self.assertTrue(payload["args"][0]["sign"])

    def test_parses_books_channel(self) -> None:
        client = OkxWebSocketClient(MarketType.SPOT)
        events = client.parse_message(
            {
                "arg": {"channel": "books", "instId": "BTC-USDT"},
                "data": [
                    {
                        "instId": "BTC-USDT",
                        "bids": [["8476.98", "415", "0", "13"]],
                        "asks": [["8477", "7", "0", "2"]],
                        "ts": "1597026383085",
                    }
                ],
            }
        )
        self.assertEqual(events[0].channel, "orderbook.update")
        self.assertEqual(events[0].payload["symbol"], "BTC/USDT")

    def test_parses_ticker_and_funding_channels(self) -> None:
        client = OkxWebSocketClient(MarketType.PERPETUAL)
        ticker_events = client.parse_message(
            {
                "arg": {"channel": "tickers", "instId": "BTC-USDT-SWAP"},
                "data": [{"instId": "BTC-USDT-SWAP", "bidPx": "100", "askPx": "101", "last": "100.5"}],
            }
        )
        funding_events = client.parse_message(
            {
                "arg": {"channel": "funding-rate", "instId": "BTC-USDT-SWAP"},
                "data": [
                    {
                        "instId": "BTC-USDT-SWAP",
                        "fundingRate": "0.0001",
                        "nextFundingRate": "0.0002",
                        "nextFundingTime": "1700000000000",
                    }
                ],
            }
        )
        self.assertEqual(ticker_events[0].channel, "ticker.update")
        self.assertEqual(ticker_events[0].payload["last"], Decimal("100.5"))
        self.assertEqual(funding_events[0].channel, "funding.update")
        self.assertEqual(funding_events[0].payload["funding_rate"], Decimal("0.0001"))


if __name__ == "__main__":
    unittest.main()
