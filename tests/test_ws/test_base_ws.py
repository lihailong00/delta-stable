from __future__ import annotations
import sys
from datetime import timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from arb.ws.base import BaseWebSocketClient, WsEvent

class _DummyWsClient(BaseWebSocketClient):

    def __init__(self) -> None:
        super().__init__('dummy', 'wss://example.invalid/ws', heartbeat_interval=30)

    def build_subscribe_message(self, channel: str, *, symbol: str | None=None, market: str | None=None) -> dict[str, object]:
        return {'op': 'subscribe', 'channel': channel, 'symbol': symbol, 'market': market}

    def parse_message(self, message: dict[str, object]) -> list[WsEvent]:
        return [WsEvent(exchange=self.exchange, channel=str(message['channel']), payload=message)]

class TestBaseWebSocketClient:

    def test_subscribe_message_contract(self) -> None:
        client = _DummyWsClient()
        payload = client.build_subscribe_message('spot.order_book', symbol='BTC/USDT')
        assert payload['op'] == 'subscribe'
        assert payload['symbol'] == 'BTC/USDT'

    def test_heartbeat_flow(self) -> None:
        client = _DummyWsClient()
        now = client.last_pong_at + timedelta(seconds=31)
        assert client.should_ping(now)
        ping = client.mark_ping(now)
        assert ping['op'] == 'ping'
        pong_time = now + timedelta(seconds=1)
        client.handle_message({'op': 'pong'})
        client.mark_pong(pong_time)
        assert not client.should_reconnect(pong_time)

    def test_reconnect_when_pong_is_stale(self) -> None:
        client = _DummyWsClient()
        future = client.last_pong_at + timedelta(seconds=61)
        assert client.should_reconnect(future)

    def test_message_parsing_emits_events(self) -> None:
        client = _DummyWsClient()
        events = client.handle_message({'channel': 'orderbook.update', 'bids': []})
        assert len(events) == 1
        assert events[0].channel == 'orderbook.update'
