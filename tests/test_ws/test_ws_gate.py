from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arb.ws.gate import GateWebSocketClient


class GateWebSocketTests(unittest.TestCase):
    def test_builds_json_subscribe_message(self) -> None:
        client = GateWebSocketClient()
        payload = client.build_subscribe_message("spot.order_book", symbol="BTC/USDT")
        self.assertEqual(payload["channel"], "spot.order_book")
        self.assertEqual(payload["event"], "subscribe")
        self.assertEqual(payload["payload"][0], "BTC_USDT")

    def test_builds_ping_message(self) -> None:
        client = GateWebSocketClient()
        payload = client.build_ping_message()
        self.assertEqual(payload["channel"], "spot.ping")

    def test_parses_orderbook_updates(self) -> None:
        client = GateWebSocketClient()
        events = client.parse_message(
            {
                "time": 1606292218,
                "channel": "spot.order_book",
                "event": "update",
                "result": {
                    "t": 1606292218213,
                    "s": "BTC_USDT",
                    "bids": [["19137.74", "0.0001"]],
                    "asks": [["19137.75", "0.6135"]],
                },
            }
        )
        self.assertEqual(events[0].channel, "orderbook.update")
        self.assertEqual(events[0].payload["symbol"], "BTC/USDT")
        self.assertEqual(events[0].payload["bids"][0][0], Decimal("19137.74"))


if __name__ == "__main__":
    unittest.main()
