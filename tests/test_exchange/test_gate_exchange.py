from __future__ import annotations
import pytest
import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock
pytestmark = pytest.mark.asyncio
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from arb.exchange.gate import GateExchange
from arb.models import MarketType, OrderStatus, PositionDirection, Side

class TestGateExchange:

    async def test_sign_request_uses_gate_signature_payload(self) -> None:
        client = GateExchange('key', 'secret', transport=AsyncMock())
        headers = client.sign_request('GET', '/spot/accounts', query='currency=BTC', body='', timestamp='1684372832')
        assert headers['KEY'] == 'key'
        assert headers['Timestamp'] == '1684372832'
        assert headers['SIGN']

    async def test_fetch_ticker_uses_spot_endpoint(self) -> None:
        transport = AsyncMock(return_value=[{'currency_pair': 'BTC_USDT', 'last': '100.5', 'lowest_ask': '101.0', 'highest_bid': '100.0'}])
        client = GateExchange('key', 'secret', transport=transport)
        ticker = await client.fetch_ticker('BTC/USDT', MarketType.SPOT)
        request = transport.await_args.args[0]
        assert request['path'] == '/spot/tickers'
        assert request['params']['currency_pair'] == 'BTC_USDT'
        assert ticker.symbol == 'BTC/USDT'
        assert ticker.ask == Decimal('101.0')

    async def test_create_order_signs_gate_private_requests(self) -> None:
        transport = AsyncMock(return_value={'id': '123456'})
        client = GateExchange('key', 'secret', transport=transport)
        order = await client.create_order('BTC/USDT', MarketType.SPOT, 'sell', Decimal('1'), price=Decimal('101'))
        request = transport.await_args.args[0]
        assert request['path'] == '/spot/orders'
        assert request['signed']
        assert request['body']['currency_pair'] == 'BTC_USDT'
        assert order.status == OrderStatus.NEW
        assert order.order_id == '123456'

    async def test_symbol_conversion_round_trip(self) -> None:
        client = GateExchange('key', 'secret', transport=AsyncMock())
        assert client.to_exchange_symbol('BTC/USDT') == 'BTC_USDT'
        assert client.from_exchange_symbol('BTC_USDT') == 'BTC/USDT'

    async def test_fetch_order_positions_and_fills_cover_private_queries(self) -> None:
        transport = AsyncMock(side_effect=[
            {'id': '1', 'contract': 'BTC_USDT', 'size': '-1', 'left': '0.6', 'price': '101', 'fill_price': '101', 'finish_as': 'open', 'reduce_only': True},
            [{'contract': 'BTC_USDT', 'size': '-1', 'entry_price': '100', 'mark_price': '99', 'unrealised_pnl': '2', 'liq_price': '120', 'leverage': '3', 'mode': 'cross'}],
            [{'id': 't1', 'order_id': '1', 'size': '-0.4', 'price': '101', 'fee': '0.02', 'role': 'maker', 'create_time_ms': '1710000000000'}],
        ])
        client = GateExchange('key', 'secret', transport=transport)
        order = await client.fetch_order('1', 'BTC/USDT', MarketType.PERPETUAL)
        positions = await client.fetch_positions(symbol='BTC/USDT')
        fills = await client.fetch_fills('1', 'BTC/USDT', MarketType.PERPETUAL)
        assert transport.await_args_list[0].args[0]['path'] == '/futures/usdt/orders/1'
        assert transport.await_args_list[1].args[0]['path'] == '/futures/usdt/positions'
        assert transport.await_args_list[2].args[0]['path'] == '/futures/usdt/my_trades'
        assert order.status == OrderStatus.NEW
        assert positions[0].direction == PositionDirection.SHORT
        assert fills[0].side == Side.SELL
