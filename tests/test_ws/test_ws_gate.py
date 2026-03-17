from __future__ import annotations
import sys
from decimal import Decimal
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from arb.ws.gate import GateWebSocketClient

class TestGateWebSocket:

    def test_builds_json_subscribe_message(self) -> None:
        client = GateWebSocketClient()
        payload = client.build_subscribe_message('spot.order_book', symbol='BTC/USDT')
        assert payload['channel'] == 'spot.order_book'
        assert payload['event'] == 'subscribe'
        assert payload['payload'][0] == 'BTC_USDT'

    def test_builds_ping_message(self) -> None:
        client = GateWebSocketClient()
        payload = client.build_ping_message()
        assert payload['channel'] == 'spot.ping'

    def test_parses_orderbook_updates(self) -> None:
        client = GateWebSocketClient()
        events = client.parse_message({'time': 1606292218, 'channel': 'spot.order_book', 'event': 'update', 'result': {'t': 1606292218213, 's': 'BTC_USDT', 'bids': [['19137.74', '0.0001']], 'asks': [['19137.75', '0.6135']]}})
        assert events[0].channel == 'orderbook.update'
        assert events[0].payload['symbol'] == 'BTC/USDT'
        assert events[0].payload['bids'][0][0] == Decimal('19137.74')

    def test_builds_private_subscribe_message(self) -> None:
        client = GateWebSocketClient(private=True)
        payload = client.build_subscribe_message('futures.orders', symbol='BTC/USDT')
        assert payload['channel'] == 'futures.orders'
        assert payload['event'] == 'subscribe'
        assert payload['payload'] == ['BTC_USDT']

    def test_parses_private_order_messages(self) -> None:
        client = GateWebSocketClient(private=True)
        events = client.parse_message({
            'channel': 'futures.orders',
            'event': 'update',
            'result': [{
                'contract': 'BTC_USDT',
                'id': '1',
                'side': 'sell',
                'status': 'finished',
                'size': '-2',
                'fill_size': '1',
                'price': '100',
            }],
        })
        assert len(events) == 1
        assert events[0].channel == 'order.update'
        assert events[0].payload['filled_quantity'] == Decimal('1')

    def test_parses_private_fill_messages(self) -> None:
        client = GateWebSocketClient(private=True)
        events = client.parse_message({
            'channel': 'futures.usertrades',
            'event': 'update',
            'result': [{
                'contract': 'BTC_USDT',
                'order_id': '1',
                'id': 'fill-1',
                'size': '-0.5',
                'price': '99.8',
                'fee': '0.01',
                'fee_currency': 'USDT',
            }],
        })
        assert len(events) == 1
        assert events[0].channel == 'fill.update'
        assert events[0].payload['side'] == 'sell'

    def test_parses_private_position_messages(self) -> None:
        client = GateWebSocketClient(private=True)
        events = client.parse_message({
            'channel': 'futures.positions',
            'event': 'update',
            'result': [{
                'contract': 'BTC_USDT',
                'size': '-3',
                'entry_price': '100',
                'mark_price': '99.5',
                'unrealised_pnl': '1.2',
            }],
        })
        assert len(events) == 1
        assert events[0].channel == 'position.update'
        assert events[0].payload['direction'] == 'short'
