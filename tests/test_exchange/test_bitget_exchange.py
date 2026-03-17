from __future__ import annotations
import pytest
import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock
pytestmark = pytest.mark.asyncio
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from arb.exchange.bitget import BitgetExchange
from arb.models import MarketType, OrderStatus, PositionDirection, Side

class TestBitgetExchange:

    async def test_sign_request_builds_bitget_headers(self) -> None:
        client = BitgetExchange('key', 'secret', 'pass', transport=AsyncMock())
        headers = client.sign_request('GET', '/api/v2/spot/account/assets', query='coin=USDT', timestamp='1700000000000')
        assert headers['ACCESS-KEY'] == 'key'
        assert headers['ACCESS-PASSPHRASE'] == 'pass'
        assert headers['ACCESS-TIMESTAMP'] == '1700000000000'
        assert headers['ACCESS-SIGN']

    async def test_fetch_ticker_uses_spot_tickers_endpoint(self) -> None:
        transport = AsyncMock(return_value={'code': '00000', 'data': [{'symbol': 'BTCUSDT', 'bidPr': '100.0', 'askPr': '101.0', 'lastPr': '100.5'}]})
        client = BitgetExchange('key', 'secret', 'pass', transport=transport)
        ticker = await client.fetch_ticker('BTC/USDT', MarketType.SPOT)
        request = transport.await_args.args[0]
        assert request['path'] == '/api/v2/spot/market/tickers'
        assert request['params']['symbol'] == 'BTCUSDT'
        assert ticker.symbol == 'BTC/USDT'
        assert ticker.bid == Decimal('100.0')

    async def test_fetch_funding_rate_parses_interval_hours(self) -> None:
        transport = AsyncMock(return_value={'code': '00000', 'data': [{'symbol': 'BTCUSDT', 'fundingRate': '0.0001', 'nextUpdate': '1700000000000', 'fundInterval': '2'}]})
        client = BitgetExchange('key', 'secret', 'pass', transport=transport)
        funding = await client.fetch_funding_rate('BTC/USDT')
        assert funding.funding_interval_hours == 2
        assert funding.rate == Decimal('0.0001')

    async def test_create_order_uses_mix_order_endpoint(self) -> None:
        transport = AsyncMock(return_value={'code': '00000', 'data': {'orderId': '12345'}})
        client = BitgetExchange('key', 'secret', 'pass', transport=transport)
        order = await client.create_order('BTC/USDT', MarketType.PERPETUAL, 'sell', Decimal('1'), price=Decimal('101'), reduce_only=True)
        request = transport.await_args.args[0]
        assert request['path'] == '/api/v2/mix/order/place-order'
        assert request['signed']
        assert request['body']['symbol'] == 'BTCUSDT'
        assert request['body']['tradeSide'] == 'close'
        assert order.status == OrderStatus.NEW
        assert order.order_id == '12345'

    async def test_fetch_order_positions_and_fills_parse_mix_payloads(self) -> None:
        transport = AsyncMock(side_effect=[
            {'code': '00000', 'data': {'symbol': 'BTCUSDT', 'side': 'sell', 'size': '1', 'price': '101', 'status': 'partial-fill', 'orderId': '1', 'filledQty': '0.4', 'priceAvg': '101', 'tradeSide': 'close'}},
            {'code': '00000', 'data': [{'symbol': 'BTCUSDT', 'holdSide': 'short', 'total': '1', 'openPriceAvg': '100', 'markPrice': '99', 'unrealizedPL': '1', 'liqPx': '120', 'leverage': '3', 'marginMode': 'cross'}]},
            {'code': '00000', 'data': [{'orderId': '1', 'tradeId': 't1', 'side': 'sell', 'fillQty': '0.4', 'fillPrice': '101', 'fee': '0.02', 'feeCoin': 'USDT', 'tradeScope': 'maker', 'fillTime': '1710000000000'}]},
        ])
        client = BitgetExchange('key', 'secret', 'pass', transport=transport)
        order = await client.fetch_order('1', 'BTC/USDT', MarketType.PERPETUAL)
        positions = await client.fetch_positions(symbol='BTC/USDT')
        fills = await client.fetch_fills('1', 'BTC/USDT', MarketType.PERPETUAL)
        assert transport.await_args_list[0].args[0]['path'] == '/api/v2/mix/order/detail'
        assert transport.await_args_list[1].args[0]['path'] == '/api/v2/mix/position/single-position'
        assert transport.await_args_list[2].args[0]['path'] == '/api/v2/mix/order/fills'
        assert order.status == OrderStatus.PARTIALLY_FILLED
        assert positions[0].direction == PositionDirection.SHORT
        assert fills[0].side == Side.SELL
