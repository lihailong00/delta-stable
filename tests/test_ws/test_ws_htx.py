from __future__ import annotations
import sys
from decimal import Decimal
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from arb.models import MarketType
from arb.ws.htx import HtxWebSocketClient

class TestHtxWebSocket:

    def test_builds_public_subscribe_message(self) -> None:
        client = HtxWebSocketClient(MarketType.SPOT)
        payload = client.build_subscribe_message('depth', symbol='BTC/USDT')
        assert payload['sub'] == 'market.btcusdt.depth.step0'

    def test_builds_auth_message(self) -> None:
        client = HtxWebSocketClient(MarketType.SPOT, api_key='key', api_secret='secret', private=True)
        payload = client.build_auth_message({'authType': 'api', 'accessKey': 'key', 'signatureMethod': 'HmacSHA256', 'signatureVersion': '2.1', 'timestamp': '2020-12-08T09:08:57', 'signature': 'abc'})
        assert payload['action'] == 'req'
        assert payload['ch'] == 'auth'
        assert payload['params']['accessKey'] == 'key'

    def test_parses_depth_channel(self) -> None:
        client = HtxWebSocketClient(MarketType.SPOT)
        events = client.parse_message({'ch': 'market.btcusdt.depth.step0', 'tick': {'bids': [[100.0, 1]], 'asks': [[101.0, 2]], 'ts': 1700000000000}})
        assert events[0].channel == 'orderbook.update'
        assert events[0].payload['symbol'] == 'BTC/USDT'

    def test_parses_ticker_channel(self) -> None:
        client = HtxWebSocketClient(MarketType.SPOT)
        events = client.parse_message({'ch': 'market.btcusdt.detail.merged', 'tick': {'bid': [100.0, 1], 'ask': [101.0, 2], 'close': 100.5}})
        assert events[0].channel == 'ticker.update'
        assert events[0].payload['last'] == Decimal('100.5')

    def test_builds_private_subscribe_message(self) -> None:
        client = HtxWebSocketClient(MarketType.PERPETUAL, private=True)
        payload = client.build_subscribe_message('orders', symbol='BTC/USDT')
        assert payload['action'] == 'sub'
        assert payload['ch'] == 'orders#BTC-USDT'

    def test_parses_private_order_messages(self) -> None:
        client = HtxWebSocketClient(MarketType.PERPETUAL, private=True)
        events = client.parse_message({
            'ch': 'orders#BTC-USDT',
            'data': {
                'contract_code': 'BTC-USDT',
                'order_id': '1',
                'direction': 'sell',
                'status': 'filled',
                'volume': '2',
                'filled_amount': '1',
                'price': '100',
            },
        })
        assert len(events) == 1
        assert events[0].channel == 'order.update'
        assert events[0].payload['symbol'] == 'BTC/USDT'

    def test_parses_private_position_messages(self) -> None:
        client = HtxWebSocketClient(MarketType.PERPETUAL, private=True)
        events = client.parse_message({
            'ch': 'positions',
            'data': {
                'contract_code': 'BTC-USDT',
                'direction': 'sell',
                'position': '-3',
                'open_price_avg': '100',
                'mark_price': '99.7',
                'profit_unreal': '0.8',
            },
        })
        assert len(events) == 1
        assert events[0].channel == 'position.update'
        assert events[0].payload['quantity'] == Decimal('3')
