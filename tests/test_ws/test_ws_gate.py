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
