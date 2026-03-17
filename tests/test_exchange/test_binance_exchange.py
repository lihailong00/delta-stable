from __future__ import annotations
import pytest
import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock
pytestmark = pytest.mark.asyncio
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from arb.exchange.binance import BinanceExchange
from arb.models import MarketType, OrderStatus, PositionDirection, Side

class TestBinanceExchange:

    async def test_sign_params_matches_expected_hmac(self) -> None:
        client = BinanceExchange('vmPUZE6mv9SD5VNHk4HlWFsOr6aKE2zvsw0MuIgwCIPy6utIco14y7Ju91duEh8A', 'NhqPtmdSJYdKjVHjA7PZj4Mge3R5YNiP1e3UZjInClVN65XAbvqqM6A7H5fATj0j', transport=AsyncMock())
        params = {'symbol': 'LTCBTC', 'side': 'BUY', 'type': 'LIMIT', 'timeInForce': 'GTC', 'quantity': '1', 'price': '0.1', 'recvWindow': '5000'}
        signed = client.sign_params(params, timestamp=1499827319559)
        assert signed['signature'] == 'c8db56825ae71d6d79447849e617115f4a920fa2acdcab2b053c4b2838bd6b71'

    async def test_fetch_ticker_uses_book_ticker_endpoint(self) -> None:
        transport = AsyncMock(return_value={'symbol': 'BTCUSDT', 'bidPrice': '100.0', 'bidQty': '1.0', 'askPrice': '101.0', 'askQty': '2.0'})
        client = BinanceExchange('key', 'secret', transport=transport)
        ticker = await client.fetch_ticker('BTC/USDT', MarketType.SPOT)
        request = transport.await_args.args[0]
        assert request['path'] == '/api/v3/ticker/bookTicker'
        assert request['params']['symbol'] == 'BTCUSDT'
        assert ticker.symbol == 'BTC/USDT'
        assert ticker.bid == Decimal('100.0')
        assert ticker.ask == Decimal('101.0')

    async def test_fetch_funding_rate_uses_premium_index(self) -> None:
        transport = AsyncMock(return_value={'symbol': 'BTCUSDT', 'markPrice': '11793.63104562', 'indexPrice': '11781.80495970', 'lastFundingRate': '0.00038246', 'nextFundingTime': 1597392000000, 'fundingIntervalHours': '4'})
        client = BinanceExchange('key', 'secret', transport=transport)
        funding = await client.fetch_funding_rate('BTC/USDT')
        request = transport.await_args.args[0]
        assert request['path'] == '/fapi/v1/premiumIndex'
        assert funding.symbol == 'BTC/USDT'
        assert funding.rate == Decimal('0.00038246')
        assert funding.funding_interval_hours == 4

    async def test_create_order_signs_private_requests(self) -> None:
        transport = AsyncMock(return_value={'symbol': 'BTCUSDT', 'side': 'SELL', 'origQty': '1', 'executedQty': '0', 'price': '101', 'status': 'NEW', 'orderId': 12345, 'avgPrice': '0'})
        client = BinanceExchange('key', 'secret', transport=transport)
        order = await client.create_order('BTC/USDT', MarketType.PERPETUAL, 'sell', Decimal('1'), price=Decimal('101'), reduce_only=True)
        request = transport.await_args.args[0]
        assert request['path'] == '/fapi/v1/order'
        assert request['signed']
        assert request['headers']['X-MBX-APIKEY'] == 'key'
        assert 'signature' in request['params']
        assert order.status == OrderStatus.NEW
        assert order.order_id == '12345'

    async def test_fetch_order_positions_and_fills_use_private_endpoints(self) -> None:
        transport = AsyncMock(side_effect=[
            {'symbol': 'BTCUSDT', 'side': 'SELL', 'origQty': '1', 'executedQty': '0.4', 'price': '101', 'status': 'PARTIALLY_FILLED', 'orderId': 12345, 'avgPrice': '101', 'reduceOnly': True},
            [{'symbol': 'BTCUSDT', 'positionAmt': '-1', 'entryPrice': '100', 'markPrice': '99', 'unRealizedProfit': '1', 'liquidationPrice': '120', 'leverage': '3', 'marginType': 'cross'}],
            [{'symbol': 'BTCUSDT', 'orderId': 12345, 'id': 9, 'price': '101', 'qty': '0.4', 'commission': '0.02', 'commissionAsset': 'USDT', 'isBuyer': False, 'isMaker': True, 'time': 1710000000000}],
        ])
        client = BinanceExchange('key', 'secret', transport=transport)
        order = await client.fetch_order('12345', 'BTC/USDT', MarketType.PERPETUAL)
        positions = await client.fetch_positions(symbol='BTC/USDT')
        fills = await client.fetch_fills('12345', 'BTC/USDT', MarketType.PERPETUAL)
        assert transport.await_args_list[0].args[0]['path'] == '/fapi/v1/order'
        assert transport.await_args_list[1].args[0]['path'] == '/fapi/v2/positionRisk'
        assert transport.await_args_list[2].args[0]['path'] == '/fapi/v1/userTrades'
        assert order.status == OrderStatus.PARTIALLY_FILLED
        assert order.filled_quantity == Decimal('0.4')
        assert positions[0].direction == PositionDirection.SHORT
        assert fills[0].side == Side.SELL
        assert fills[0].fee_asset == 'USDT'
