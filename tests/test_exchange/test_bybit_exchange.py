from __future__ import annotations
import pytest
import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock
pytestmark = pytest.mark.asyncio
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from arb.exchange.bybit import BybitExchange
from arb.models import MarketType, OrderStatus

class TestBybitExchange:

    async def test_sign_request_builds_bybit_headers(self) -> None:
        client = BybitExchange('key', 'secret', transport=AsyncMock())
        headers = client.sign_request('GET', '/v5/order/realtime', query='category=spot&symbol=BTCUSDT', timestamp='1658384314791')
        assert headers['X-BAPI-API-KEY'] == 'key'
        assert headers['X-BAPI-TIMESTAMP'] == '1658384314791'
        assert headers['X-BAPI-RECV-WINDOW'] == '5000'
        assert headers['X-BAPI-SIGN']

    async def test_fetch_ticker_uses_v5_market_tickers(self) -> None:
        transport = AsyncMock(return_value={'retCode': 0, 'result': {'list': [{'symbol': 'BTCUSDT', 'bid1Price': '100.0', 'ask1Price': '101.0', 'lastPrice': '100.5'}]}})
        client = BybitExchange('key', 'secret', transport=transport)
        ticker = await client.fetch_ticker('BTC/USDT', MarketType.SPOT)
        request = transport.await_args.args[0]
        assert request['path'] == '/v5/market/tickers'
        assert request['params']['category'] == 'spot'
        assert request['params']['symbol'] == 'BTCUSDT'
        assert ticker.symbol == 'BTC/USDT'
        assert ticker.last == Decimal('100.5')

    async def test_build_ws_auth_message(self) -> None:
        client = BybitExchange('key', 'secret', transport=AsyncMock())
        payload = client.build_ws_auth_message(1662350400000)
        assert payload['op'] == 'auth'
        assert payload['args'][0] == 'key'
        assert payload['args'][1] == 1662350400000
        assert payload['args'][2]

    async def test_create_order_uses_private_endpoint(self) -> None:
        transport = AsyncMock(return_value={'retCode': 0, 'result': {'orderId': 'abc123'}})
        client = BybitExchange('key', 'secret', transport=transport)
        order = await client.create_order('BTC/USDT', MarketType.PERPETUAL, 'sell', Decimal('1'), price=Decimal('101'), reduce_only=True)
        request = transport.await_args.args[0]
        assert request['path'] == '/v5/order/create'
        assert request['signed']
        assert request['body']['category'] == 'linear'
        assert request['body']['symbol'] == 'BTCUSDT'
        assert order.status == OrderStatus.NEW
        assert order.order_id == 'abc123'
