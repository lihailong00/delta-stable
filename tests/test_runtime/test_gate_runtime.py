from __future__ import annotations
import pytest
import sys
from pathlib import Path
pytestmark = pytest.mark.asyncio
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from arb.models import MarketType
from arb.net.http import HttpTransport
from arb.runtime.gate_runtime import GateRuntime

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

class TestGateRuntime:

    async def test_public_ping_uses_live_http_transport(self) -> None:
        client = _HttpClient([_Response([{'id': 'BTC_USDT'}])])
        runtime = GateRuntime.build(api_key='key', api_secret='secret', http_transport=HttpTransport(client=client), ws_connector=lambda endpoint: None)
        assert await runtime.public_ping()
        assert client.calls[0][1] == 'https://api.gateio.ws/api/v4/spot/currency_pairs'

    async def test_private_balance_check_uses_exchange_adapter(self) -> None:
        client = _HttpClient([_Response([{'currency': 'USDT', 'available': '100.5', 'locked': '1.5'}, {'currency': 'BTC', 'available': '0.25', 'locked': '0.0'}])])
        runtime = GateRuntime.build(api_key='key', api_secret='secret', http_transport=HttpTransport(client=client), ws_connector=lambda endpoint: None)
        balances = await runtime.validate_private_access()
        assert balances['USDT'] == '102.0'
        assert balances['BTC'] == '0.25'

    async def test_ws_orderbook_stream_uses_public_subscription(self) -> None:
        ws = _WebSocket([{'channel': 'spot.order_book', 'result': {'s': 'BTC_USDT', 'bids': [['100.0', '1']], 'asks': [['101.0', '2']], 't': 123}}])

        async def connector(endpoint: str):
            return ws
        runtime = GateRuntime.build(api_key='key', api_secret='secret', http_transport=HttpTransport(client=_HttpClient([])), ws_connector=connector)
        events = await runtime.stream_orderbook('BTC/USDT')
        assert ws.sent[0]['channel'] == 'spot.order_book'
        assert events[0]['channel'] == 'orderbook.update'
        assert events[0]['payload']['symbol'] == 'BTC/USDT'

    async def test_fetch_public_snapshot_uses_collector(self) -> None:
        client = _HttpClient([_Response([{'currency_pair': 'BTC_USDT', 'highest_bid': '100.0', 'lowest_ask': '101.0', 'last': '100.5'}]), _Response({'bids': [['100.0', '1']], 'asks': [['101.0', '2']]})])
        runtime = GateRuntime.build(api_key='key', api_secret='secret', http_transport=HttpTransport(client=client), ws_connector=lambda endpoint: None)
        snapshot = await runtime.fetch_public_snapshot('BTC/USDT', MarketType.SPOT)
        assert snapshot['ticker']['symbol'] == 'BTC/USDT'
        assert snapshot['orderbook']['exchange'] == 'gate'
