from __future__ import annotations
import sys
from decimal import Decimal
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from arb.models import MarketType
from arb.ws.binance import BinanceWebSocketClient

class TestBinanceWebSocket:

    def test_builds_json_subscribe_messages(self) -> None:
        client = BinanceWebSocketClient(MarketType.SPOT)
        payload = client.build_subscribe_message('bookTicker', symbol='BTC/USDT')
        assert payload['method'] == 'SUBSCRIBE'
        assert payload['params'] == ['btcusdt@bookTicker']

    def test_parses_book_ticker_updates(self) -> None:
        client = BinanceWebSocketClient(MarketType.SPOT)
        events = client.parse_message({'s': 'BTCUSDT', 'b': '25.35190000', 'B': '31.21000000', 'a': '25.36520000', 'A': '40.66000000'})
        assert len(events) == 1
        assert events[0].channel == 'orderbook.ticker'
        assert events[0].payload['symbol'] == 'BTC/USDT'
        assert events[0].payload['best_bid'] == Decimal('25.35190000')

    def test_parses_depth_updates(self) -> None:
        client = BinanceWebSocketClient(MarketType.SPOT)
        events = client.parse_message({'e': 'depthUpdate', 's': 'BNBUSDT', 'U': 157, 'u': 160, 'b': [['0.0024', '10']], 'a': [['0.0026', '100']]})
        assert events[0].channel == 'orderbook.update'
        assert events[0].payload['symbol'] == 'BNB/USDT'

    def test_parses_mark_price_updates(self) -> None:
        client = BinanceWebSocketClient(MarketType.PERPETUAL)
        events = client.parse_message({'e': 'markPriceUpdate', 's': 'BTCUSDT', 'p': '11794.15000000', 'i': '11784.62659091', 'r': '0.00038167', 'T': 1562306400000})
        assert events[0].channel == 'funding.update'
        assert events[0].payload['funding_rate'] == Decimal('0.00038167')

    def test_builds_private_subscribe_message(self) -> None:
        client = BinanceWebSocketClient(MarketType.PERPETUAL, private=True, listen_key='listen-key')
        payload = client.build_subscribe_message('orders')
        assert payload['method'] == 'SUBSCRIBE'
        assert payload['params'] == ['listen-key']

    def test_parses_private_execution_report(self) -> None:
        client = BinanceWebSocketClient(MarketType.SPOT, private=True, listen_key='listen-key')
        events = client.parse_message({
            'e': 'executionReport',
            's': 'BTCUSDT',
            'i': 123,
            'S': 'BUY',
            'X': 'FILLED',
            'q': '1.5',
            'z': '1.5',
            'p': '100.0',
            'l': '0.5',
            'L': '100.1',
            't': 987,
            'n': '0.01',
            'N': 'USDT',
        })
        assert [event.channel for event in events] == ['order.update', 'fill.update']
        assert events[0].payload['status'] == 'filled'
        assert events[1].payload['quantity'] == Decimal('0.5')

    def test_parses_private_account_update(self) -> None:
        client = BinanceWebSocketClient(MarketType.PERPETUAL, private=True, listen_key='listen-key')
        events = client.parse_message({
            'e': 'ACCOUNT_UPDATE',
            'a': {
                'P': [
                    {'s': 'BTCUSDT', 'pa': '-2', 'ep': '101', 'mp': '100', 'up': '2.5'},
                    {'s': 'ETHUSDT', 'pa': '0', 'ep': '0', 'mp': '0', 'up': '0'},
                ]
            },
        })
        assert len(events) == 1
        assert events[0].channel == 'position.update'
        assert events[0].payload['direction'] == 'short'

    def test_parses_private_futures_order_update(self) -> None:
        client = BinanceWebSocketClient(MarketType.PERPETUAL, private=True, listen_key='listen-key')
        events = client.parse_message({
            'e': 'ORDER_TRADE_UPDATE',
            'o': {
                's': 'BTCUSDT',
                'i': 321,
                'S': 'SELL',
                'X': 'PARTIALLY_FILLED',
                'q': '2',
                'z': '1',
                'p': '100',
                'l': '1',
                'L': '99.9',
                't': 654,
                'n': '0.02',
                'N': 'USDT',
            },
        })
        assert [event.channel for event in events] == ['order.update', 'fill.update']
        assert events[0].payload['filled_quantity'] == Decimal('1')
