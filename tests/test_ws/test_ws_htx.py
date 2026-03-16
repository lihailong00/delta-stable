from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arb.models import MarketType
from arb.ws.htx import HtxWebSocketClient


class HtxWebSocketTests(unittest.TestCase):
    def test_builds_public_subscribe_message(self) -> None:
        client = HtxWebSocketClient(MarketType.SPOT)
        payload = client.build_subscribe_message("depth", symbol="BTC/USDT")
        self.assertEqual(payload["sub"], "market.btcusdt.depth.step0")

    def test_builds_auth_message(self) -> None:
        client = HtxWebSocketClient(MarketType.SPOT, api_key="key", api_secret="secret", private=True)
        payload = client.build_auth_message(
            {
                "authType": "api",
                "accessKey": "key",
                "signatureMethod": "HmacSHA256",
                "signatureVersion": "2.1",
                "timestamp": "2020-12-08T09:08:57",
                "signature": "abc",
            }
        )
        self.assertEqual(payload["action"], "req")
        self.assertEqual(payload["ch"], "auth")
        self.assertEqual(payload["params"]["accessKey"], "key")

    def test_parses_depth_channel(self) -> None:
        client = HtxWebSocketClient(MarketType.SPOT)
        events = client.parse_message(
            {
                "ch": "market.btcusdt.depth.step0",
                "tick": {
                    "bids": [[100.0, 1]],
                    "asks": [[101.0, 2]],
                    "ts": 1700000000000,
                },
            }
        )
        self.assertEqual(events[0].channel, "orderbook.update")
        self.assertEqual(events[0].payload["symbol"], "BTC/USDT")

    def test_parses_ticker_channel(self) -> None:
        client = HtxWebSocketClient(MarketType.SPOT)
        events = client.parse_message(
            {
                "ch": "market.btcusdt.detail.merged",
                "tick": {
                    "bid": [100.0, 1],
                    "ask": [101.0, 2],
                    "close": 100.5,
                },
            }
        )
        self.assertEqual(events[0].channel, "ticker.update")
        self.assertEqual(events[0].payload["last"], Decimal("100.5"))


if __name__ == "__main__":
    unittest.main()
