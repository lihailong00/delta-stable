from __future__ import annotations
import pytest
import sys
from pathlib import Path
pytestmark = pytest.mark.asyncio
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from arb.models import MarketType
from arb.net.http import HttpTransport
from arb.runtime.bitget_runtime import BitgetRuntime

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

class TestBitgetRuntime:

    async def test_public_ping_uses_live_http_transport(self) -> None:
        client = _HttpClient([_Response({'code': '00000', 'data': {'serverTime': '123'}})])
        runtime = BitgetRuntime.build(api_key='key', api_secret='secret', passphrase='pass', http_transport=HttpTransport(client=client), ws_connector=lambda endpoint: None)
        assert await runtime.public_ping()
        assert client.calls[0][1] == 'https://api.bitget.com/api/v2/public/time'

    async def test_private_balance_check_uses_exchange_adapter(self) -> None:
        client = _HttpClient([_Response({'code': '00000', 'data': [{'coin': 'USDT', 'available': '100.5', 'frozen': '1.5', 'locked': '0'}, {'coin': 'BTC', 'available': '0.25', 'frozen': '0', 'locked': '0'}]})])
        runtime = BitgetRuntime.build(api_key='key', api_secret='secret', passphrase='pass', http_transport=HttpTransport(client=client), ws_connector=lambda endpoint: None)
        balances = await runtime.validate_private_access()
        assert balances['USDT'] == '102.0'
        assert balances['BTC'] == '0.25'

    async def test_private_login_and_orderbook_stream(self) -> None:
        public_ws = _WebSocket([{'arg': {'instType': 'SPOT', 'channel': 'books', 'instId': 'BTCUSDT'}, 'data': [{'bids': [['100.0', '1']], 'asks': [['101.0', '2']], 'ts': '1700000000000'}]}])
        private_ws = _WebSocket([{'event': 'login', 'code': '0'}])
        sockets = {'wss://ws.bitget.com/v2/ws/public': public_ws, 'wss://ws.bitget.com/v2/ws/private': private_ws}

        async def connector(endpoint: str):
            return sockets[endpoint]
        runtime = BitgetRuntime.build(api_key='key', api_secret='secret', passphrase='pass', market_type=MarketType.SPOT, http_transport=HttpTransport(client=_HttpClient([])), ws_connector=connector)
        login_message = runtime.build_private_login_message('1700000000000')
        assert login_message['op'] == 'login'
        await runtime.login_private_ws('1700000000000')
        events = await runtime.stream_orderbook('BTC/USDT')
        assert private_ws.sent[0]['op'] == 'login'
        assert events[0]['channel'] == 'orderbook.update'
        assert events[0]['payload']['symbol'] == 'BTC/USDT'

    async def test_stream_funding_uses_public_ws_subscription(self) -> None:
        ws = _WebSocket([{'arg': {'instType': 'USDT-FUTURES', 'channel': 'ticker', 'instId': 'BTCUSDT'}, 'data': [{'instId': 'BTCUSDT', 'bidPr': '100.0', 'askPr': '101.0', 'lastPr': '100.5', 'fundingRate': '0.0001', 'nextFundingTime': '1700003600000', 'markPrice': '100.4'}]}])

        async def connector(endpoint: str):
            return ws
        runtime = BitgetRuntime.build(api_key='key', api_secret='secret', passphrase='pass', market_type=MarketType.PERPETUAL, http_transport=HttpTransport(client=_HttpClient([])), ws_connector=connector)
        events = await runtime.stream_funding('BTC/USDT')
        assert ws.sent[0]['args'][0]['channel'] == 'ticker'
        assert events[1]['channel'] == 'funding.update'
        assert events[1]['payload']['symbol'] == 'BTC/USDT'
