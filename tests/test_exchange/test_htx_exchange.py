from __future__ import annotations
import pytest
import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock
pytestmark = pytest.mark.asyncio
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from arb.exchange.htx import HtxExchange
from arb.models import MarketType, OrderStatus, PositionDirection, Side

class TestHtxExchange:

    async def test_sign_request_builds_huobi_query_params(self) -> None:
        client = HtxExchange('key', 'secret', transport=AsyncMock())
        params = client.sign_request('GET', '/v1/account/accounts', host='api.huobi.pro', timestamp='2020-12-08T09:08:57')
        assert params['AccessKeyId'] == 'key'
        assert params['SignatureMethod'] == 'HmacSHA256'
        assert params['SignatureVersion'] == '2'
        assert params['Timestamp'] == '2020-12-08T09:08:57'
        assert params['Signature']

    async def test_fetch_ticker_uses_spot_merged_endpoint(self) -> None:
        transport = AsyncMock(return_value={'status': 'ok', 'tick': {'bid': [100.0, 1], 'ask': [101.0, 2], 'close': 100.5}})
        client = HtxExchange('key', 'secret', transport=transport)
        ticker = await client.fetch_ticker('BTC/USDT', MarketType.SPOT)
        request = transport.await_args.args[0]
        assert request['path'] == '/market/detail/merged'
        assert request['params']['symbol'] == 'btcusdt'
        assert ticker.symbol == 'BTC/USDT'
        assert ticker.bid == Decimal('100.0')

    async def test_fetch_funding_rate_parses_interval_hours(self) -> None:
        transport = AsyncMock(return_value={'status': 'ok', 'data': {'contract_code': 'BTC-USDT', 'funding_rate': '0.0001', 'estimated_rate': '0.0002', 'next_funding_time': '1700000000000', 'funding_interval_hours': '1'}})
        client = HtxExchange('key', 'secret', transport=transport)
        funding = await client.fetch_funding_rate('BTC/USDT')
        assert funding.funding_interval_hours == 1
        assert funding.rate == Decimal('0.0001')

    async def test_build_ws_auth_params(self) -> None:
        client = HtxExchange('key', 'secret', transport=AsyncMock())
        params = client.build_ws_auth_params(timestamp='2020-12-08T09:08:57')
        assert params['accessKey'] == 'key'
        assert params['signatureMethod'] == 'HmacSHA256'
        assert params['signatureVersion'] == '2.1'
        assert params['signature']

    async def test_create_order_uses_swap_order_endpoint(self) -> None:
        transport = AsyncMock(return_value={'status': 'ok', 'data': {'order_id_str': '312269865356374016'}})
        client = HtxExchange('key', 'secret', transport=transport)
        order = await client.create_order('BTC/USDT', MarketType.PERPETUAL, 'sell', Decimal('1'), price=Decimal('101'), reduce_only=True)
        request = transport.await_args.args[0]
        assert request['path'] == '/linear-swap-api/v1/swap_order'
        assert request['signed']
        assert request['body']['contract_code'] == 'BTC-USDT'
        assert request['body']['offset'] == 'close'
        assert order.status == OrderStatus.NEW
        assert order.order_id == '312269865356374016'

    async def test_fetch_order_positions_and_fills_parse_swap_payloads(self) -> None:
        transport = AsyncMock(side_effect=[
            {'status': 'ok', 'data': [{'contract_code': 'BTC-USDT', 'direction': 'sell', 'offset': 'close', 'volume': 1, 'price': '101', 'status': 'partially_filled', 'order_id_str': '1', 'trade_volume': '0.4', 'trade_avg_price': '101'}]},
            {'status': 'ok', 'data': [{'contract_code': 'BTC-USDT', 'direction': 'sell', 'volume': '1', 'cost_open': '100', 'last_price': '99', 'profit_unreal': '1', 'liquidation_price': '120', 'lever_rate': '3'}]},
            {'status': 'ok', 'data': {'trades': [{'direction': 'sell', 'trade_volume': '0.4', 'trade_price': '101', 'order_id': '1', 'trade_id': 't1', 'trade_fee': '0.02', 'create_date': '1710000000000'}]}},
        ])
        client = HtxExchange('key', 'secret', transport=transport)
        order = await client.fetch_order('1', 'BTC/USDT', MarketType.PERPETUAL)
        positions = await client.fetch_positions(symbol='BTC/USDT')
        fills = await client.fetch_fills('1', 'BTC/USDT', MarketType.PERPETUAL)
        assert transport.await_args_list[0].args[0]['path'] == '/linear-swap-api/v1/swap_order_info'
        assert transport.await_args_list[1].args[0]['path'] == '/linear-swap-api/v1/swap_position_info'
        assert transport.await_args_list[2].args[0]['path'] == '/linear-swap-api/v1/swap_order_detail'
        assert order.status == OrderStatus.PARTIALLY_FILLED
        assert positions[0].direction == PositionDirection.SHORT
        assert fills[0].side == Side.SELL
