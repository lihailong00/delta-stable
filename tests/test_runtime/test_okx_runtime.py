from __future__ import annotations

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arb.models import MarketType
from arb.net.http import HttpTransport
from arb.runtime.okx_runtime import OkxRuntime


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


class OkxRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_ping_uses_live_http_transport(self) -> None:
        client = _HttpClient([_Response({"data": [{"ts": "123"}]})])
        runtime = OkxRuntime.build(
            api_key="key",
            api_secret="secret",
            passphrase="pass",
            http_transport=HttpTransport(client=client),
            ws_connector=lambda endpoint: None,
        )
        self.assertTrue(await runtime.public_ping())
        self.assertEqual(client.calls[0][1], "https://www.okx.com/api/v5/public/time")

    async def test_private_balance_check_uses_exchange_adapter(self) -> None:
        client = _HttpClient(
            [
                _Response(
                    {
                        "data": [
                            {
                                "details": [
                                    {"ccy": "USDT", "cashBal": "100.5"},
                                    {"ccy": "BTC", "cashBal": "0.25"},
                                ]
                            }
                        ]
                    }
                )
            ]
        )
        runtime = OkxRuntime.build(
            api_key="key",
            api_secret="secret",
            passphrase="pass",
            http_transport=HttpTransport(client=client),
            ws_connector=lambda endpoint: None,
        )
        balances = await runtime.validate_private_access()
        self.assertEqual(balances["USDT"], "100.5")
        self.assertEqual(balances["BTC"], "0.25")

    async def test_private_login_message_and_orderbook_stream(self) -> None:
        public_ws = _WebSocket(
            [
                {
                    "arg": {"channel": "books", "instId": "BTC-USDT"},
                    "data": [
                        {
                            "instId": "BTC-USDT",
                            "bids": [["100.0", "1"]],
                            "asks": [["101.0", "2"]],
                            "ts": "123",
                        }
                    ],
                }
            ]
        )
        private_ws = _WebSocket([{"event": "login", "code": "0"}])
        sockets = {
            "wss://ws.okx.com:8443/ws/v5/public": public_ws,
            "wss://ws.okx.com:8443/ws/v5/private": private_ws,
        }

        async def connector(endpoint: str):
            return sockets[endpoint]

        runtime = OkxRuntime.build(
            api_key="key",
            api_secret="secret",
            passphrase="pass",
            market_type=MarketType.SPOT,
            http_transport=HttpTransport(client=_HttpClient([])),
            ws_connector=connector,
        )
        login_message = runtime.build_private_login_message("123")
        self.assertEqual(login_message["op"], "login")

        await runtime.login_private_ws("123")
        events = await runtime.stream_orderbook("BTC/USDT")
        self.assertEqual(private_ws.sent[0]["op"], "login")
        self.assertEqual(events[0]["channel"], "orderbook.update")
        self.assertEqual(events[0]["payload"]["symbol"], "BTC/USDT")

    async def test_stream_funding_uses_public_ws_subscription(self) -> None:
        ws = _WebSocket(
            [
                {
                    "arg": {"channel": "funding-rate", "instId": "BTC-USDT-SWAP"},
                    "data": [
                        {
                            "instId": "BTC-USDT-SWAP",
                            "fundingRate": "0.0001",
                            "nextFundingRate": "0.0002",
                            "nextFundingTime": "123456789",
                        }
                    ],
                }
            ]
        )

        async def connector(endpoint: str):
            return ws

        runtime = OkxRuntime.build(
            api_key="key",
            api_secret="secret",
            passphrase="pass",
            market_type=MarketType.PERPETUAL,
            http_transport=HttpTransport(client=_HttpClient([])),
            ws_connector=connector,
        )
        events = await runtime.stream_funding("BTC/USDT")
        self.assertEqual(ws.sent[0]["args"][0]["channel"], "funding-rate")
        self.assertEqual(events[0]["channel"], "funding.update")
        self.assertEqual(events[0]["payload"]["symbol"], "BTC/USDT")


if __name__ == "__main__":
    unittest.main()
