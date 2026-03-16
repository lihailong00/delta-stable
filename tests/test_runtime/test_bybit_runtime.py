from __future__ import annotations

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arb.models import MarketType
from arb.net.http import HttpTransport
from arb.runtime.bybit_runtime import BybitRuntime


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


class BybitRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_ping_uses_live_http_transport(self) -> None:
        client = _HttpClient([_Response({"result": {"timeSecond": "123"}})])
        runtime = BybitRuntime.build(
            api_key="key",
            api_secret="secret",
            http_transport=HttpTransport(client=client),
            ws_connector=lambda endpoint: None,
        )
        self.assertTrue(await runtime.public_ping())
        self.assertEqual(client.calls[0][1], "https://api.bybit.com/v5/market/time")

    async def test_private_balance_check_uses_exchange_adapter(self) -> None:
        client = _HttpClient(
            [
                _Response(
                    {
                        "result": {
                            "list": [
                                {
                                    "coin": [
                                        {"coin": "USDT", "walletBalance": "100.5"},
                                        {"coin": "BTC", "walletBalance": "0.25"},
                                    ]
                                }
                            ]
                        }
                    }
                )
            ]
        )
        runtime = BybitRuntime.build(
            api_key="key",
            api_secret="secret",
            http_transport=HttpTransport(client=client),
            ws_connector=lambda endpoint: None,
        )
        balances = await runtime.validate_private_access()
        self.assertEqual(balances["USDT"], "100.5")
        self.assertEqual(balances["BTC"], "0.25")

    async def test_private_auth_and_orderbook_stream(self) -> None:
        public_ws = _WebSocket(
            [
                {
                    "topic": "orderbook.50.BTCUSDT",
                    "type": "snapshot",
                    "data": {
                        "s": "BTCUSDT",
                        "b": [["100.0", "1"]],
                        "a": [["101.0", "2"]],
                        "u": 123,
                    },
                }
            ]
        )
        private_ws = _WebSocket([{"success": True, "op": "auth"}])
        sockets = {
            "wss://stream.bybit.com/v5/public/spot": public_ws,
            "wss://stream.bybit.com/v5/private": private_ws,
        }

        async def connector(endpoint: str):
            return sockets[endpoint]

        runtime = BybitRuntime.build(
            api_key="key",
            api_secret="secret",
            market_type=MarketType.SPOT,
            http_transport=HttpTransport(client=_HttpClient([])),
            ws_connector=connector,
        )
        auth_message = runtime.build_private_auth_message(123456)
        self.assertEqual(auth_message["op"], "auth")

        await runtime.auth_private_ws(123456)
        events = await runtime.stream_orderbook("BTC/USDT")
        self.assertEqual(private_ws.sent[0]["op"], "auth")
        self.assertEqual(events[0]["channel"], "orderbook.update")
        self.assertEqual(events[0]["payload"]["symbol"], "BTC/USDT")

    async def test_stream_ticker_uses_public_ws_subscription(self) -> None:
        ws = _WebSocket(
            [
                {
                    "topic": "tickers.BTCUSDT",
                    "data": {
                        "symbol": "BTCUSDT",
                        "bid1Price": "100.0",
                        "ask1Price": "101.0",
                        "lastPrice": "100.5",
                        "fundingRate": "0.0001",
                    },
                }
            ]
        )

        async def connector(endpoint: str):
            return ws

        runtime = BybitRuntime.build(
            api_key="key",
            api_secret="secret",
            market_type=MarketType.PERPETUAL,
            http_transport=HttpTransport(client=_HttpClient([])),
            ws_connector=connector,
        )
        events = await runtime.stream_ticker("BTC/USDT")
        self.assertEqual(ws.sent[0]["args"][0], "tickers.BTCUSDT")
        self.assertEqual(events[0]["channel"], "ticker.update")
        self.assertEqual(events[0]["payload"]["symbol"], "BTC/USDT")


if __name__ == "__main__":
    unittest.main()
