from __future__ import annotations

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arb.models import MarketType
from arb.net.http import HttpTransport
from arb.runtime.htx_runtime import HtxRuntime


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


class HtxRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_ping_uses_live_http_transport(self) -> None:
        client = _HttpClient([_Response({"status": "ok", "data": 1700000000000})])
        runtime = HtxRuntime.build(
            api_key="key",
            api_secret="secret",
            http_transport=HttpTransport(client=client),
            ws_connector=lambda endpoint: None,
        )
        self.assertTrue(await runtime.public_ping())
        self.assertEqual(client.calls[0][1], "https://api.huobi.pro/v1/common/timestamp")

    async def test_private_balance_check_uses_exchange_adapter(self) -> None:
        client = _HttpClient(
            [
                _Response({"status": "ok", "data": [{"id": 1001, "type": "spot"}]}),
                _Response(
                    {
                        "status": "ok",
                        "data": {
                            "list": [
                                {"currency": "usdt", "balance": "100.5"},
                                {"currency": "usdt", "balance": "1.5"},
                                {"currency": "btc", "balance": "0.25"},
                            ]
                        },
                    }
                ),
            ]
        )
        runtime = HtxRuntime.build(
            api_key="key",
            api_secret="secret",
            http_transport=HttpTransport(client=client),
            ws_connector=lambda endpoint: None,
        )
        balances = await runtime.validate_private_access()
        self.assertEqual(balances["USDT"], "102.0")
        self.assertEqual(balances["BTC"], "0.25")

    async def test_ws_depth_subscription_streams_normalized_events(self) -> None:
        ws = _WebSocket(
            [
                {
                    "ch": "market.btcusdt.depth.step0",
                    "tick": {
                        "bids": [[100.0, 1]],
                        "asks": [[101.0, 2]],
                        "ts": 1700000000000,
                    },
                }
            ]
        )

        async def connector(endpoint: str):
            return ws

        runtime = HtxRuntime.build(
            api_key="key",
            api_secret="secret",
            market_type=MarketType.SPOT,
            http_transport=HttpTransport(client=_HttpClient([])),
            ws_connector=connector,
        )
        events = await runtime.stream_orderbook("BTC/USDT")
        self.assertEqual(ws.sent[0]["sub"], "market.btcusdt.depth.step0")
        self.assertEqual(events[0]["channel"], "orderbook.update")
        self.assertEqual(events[0]["payload"]["symbol"], "BTC/USDT")

    async def test_stream_ticker_uses_public_ws_subscription(self) -> None:
        ws = _WebSocket(
            [
                {
                    "ch": "market.btcusdt.detail.merged",
                    "tick": {
                        "bid": [100.0, 1],
                        "ask": [101.0, 2],
                        "close": 100.5,
                    },
                }
            ]
        )

        async def connector(endpoint: str):
            return ws

        runtime = HtxRuntime.build(
            api_key="key",
            api_secret="secret",
            market_type=MarketType.SPOT,
            http_transport=HttpTransport(client=_HttpClient([])),
            ws_connector=connector,
        )
        events = await runtime.stream_ticker("BTC/USDT")
        self.assertEqual(ws.sent[0]["sub"], "market.btcusdt.detail.merged")
        self.assertEqual(events[0]["channel"], "ticker.update")
        self.assertEqual(events[0]["payload"]["symbol"], "BTC/USDT")


if __name__ == "__main__":
    unittest.main()
