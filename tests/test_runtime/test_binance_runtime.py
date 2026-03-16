from __future__ import annotations

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arb.models import MarketType
from arb.net.http import HttpTransport
from arb.runtime.binance_runtime import BinanceRuntime


class _Response:
    def __init__(self, payload):
        self.status_code = 200
        self._payload = payload

    def json(self):
        return self._payload


class _HttpClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


class _WebSocket:
    def __init__(self, messages):
        self.messages = list(messages)
        self.sent = []

    async def send(self, message):
        self.sent.append(message)

    async def recv(self):
        return self.messages.pop(0)

    async def close(self):
        return None


class BinanceRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_ping_uses_live_http_transport(self) -> None:
        client = _HttpClient([_Response({})])
        runtime = BinanceRuntime.build(
            api_key="key",
            api_secret="secret",
            http_transport=HttpTransport(client=client),
            ws_connector=lambda endpoint: None,
        )
        self.assertTrue(await runtime.public_ping())
        self.assertEqual(client.calls[0][1], "https://api.binance.com/api/v3/ping")

    async def test_private_balance_check_uses_exchange_adapter(self) -> None:
        client = _HttpClient(
            [
                _Response(
                    {
                        "balances": [
                            {"asset": "USDT", "free": "100.0", "locked": "1.0"},
                        ]
                    }
                )
            ]
        )
        runtime = BinanceRuntime.build(
            api_key="key",
            api_secret="secret",
            http_transport=HttpTransport(client=client),
            ws_connector=lambda endpoint: None,
        )
        balances = await runtime.validate_private_access()
        self.assertEqual(balances["USDT"], "101.0")

    async def test_ws_depth_subscription_streams_normalized_events(self) -> None:
        ws = _WebSocket(
            [
                {
                    "e": "depthUpdate",
                    "s": "BTCUSDT",
                    "U": 157,
                    "u": 160,
                    "b": [["100.0", "1"]],
                    "a": [["101.0", "2"]],
                }
            ]
        )

        async def connector(endpoint: str):
            return ws

        http_client = _HttpClient([])
        runtime = BinanceRuntime.build(
            api_key="key",
            api_secret="secret",
            market_type=MarketType.SPOT,
            http_transport=HttpTransport(client=http_client),
            ws_connector=connector,
        )
        events = await runtime.stream_orderbook("BTC/USDT")
        self.assertEqual(events[0]["channel"], "orderbook.update")
        self.assertEqual(events[0]["payload"]["symbol"], "BTC/USDT")
        self.assertEqual(len(ws.sent), 1)


if __name__ == "__main__":
    unittest.main()
