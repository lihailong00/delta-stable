from __future__ import annotations
import pytest
import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock
pytestmark = pytest.mark.asyncio
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from arb.exchange.bybit import BybitExchange
from arb.models import MarketType, OrderStatus, PositionDirection, Side

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

    async def test_fetch_funding_rate_parses_interval_hours(self) -> None:
        transport = AsyncMock(return_value={'retCode': 0, 'result': {'list': [{'symbol': 'BTCUSDT', 'fundingRate': '0.0001', 'nextFundingTime': '1700000000000', 'fundingIntervalHour': '2'}]}})
        client = BybitExchange('key', 'secret', transport=transport)
        funding = await client.fetch_funding_rate('BTC/USDT')
        assert funding.funding_interval_hours == 2
        assert funding.rate == Decimal('0.0001')

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

    async def test_fetch_order_positions_and_fills_parse_realtime_payloads(self) -> None:
        transport = AsyncMock(side_effect=[
            {'retCode': 0, 'result': {'list': [{'symbol': 'BTCUSDT', 'side': 'Sell', 'qty': '1', 'price': '101', 'orderStatus': 'PartiallyFilled', 'orderId': 'o1', 'cumExecQty': '0.4', 'avgPrice': '101', 'reduceOnly': True}]}},
            {'retCode': 0, 'result': {'list': [{'symbol': 'BTCUSDT', 'side': 'Sell', 'size': '1', 'avgPrice': '100', 'markPrice': '99', 'unrealisedPnl': '1', 'liqPrice': '120', 'leverage': '3', 'tradeMode': 'cross', 'positionIdx': 2}]}},
            {'retCode': 0, 'result': {'list': [{'symbol': 'BTCUSDT', 'side': 'Sell', 'execQty': '0.4', 'execPrice': '101', 'orderId': 'o1', 'execId': 'e1', 'execFee': '0.02', 'feeCurrency': 'USDT', 'execType': 'TradeMaker', 'execTime': '1710000000000'}]}},
        ])
        client = BybitExchange('key', 'secret', transport=transport)
        order = await client.fetch_order('o1', 'BTC/USDT', MarketType.PERPETUAL)
        positions = await client.fetch_positions(symbol='BTC/USDT')
        fills = await client.fetch_fills('o1', 'BTC/USDT', MarketType.PERPETUAL)
        assert transport.await_args_list[0].args[0]['path'] == '/v5/order/realtime'
        assert transport.await_args_list[1].args[0]['path'] == '/v5/position/list'
        assert transport.await_args_list[2].args[0]['path'] == '/v5/execution/list'
        assert order.status == OrderStatus.PARTIALLY_FILLED
        assert positions[0].direction == PositionDirection.SHORT
        assert fills[0].side == Side.SELL
