from __future__ import annotations
import sys
from decimal import Decimal
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from arb.models import MarketType
from arb.ws.bitget import BitgetWebSocketClient

class TestBitgetWebSocket:

    def test_builds_public_subscribe_message(self) -> None:
        client = BitgetWebSocketClient(MarketType.SPOT)
        payload = client.build_subscribe_message('books', symbol='BTC/USDT')
        assert payload['op'] == 'subscribe'
        assert payload['args'][0]['instType'] == 'SPOT'
        assert payload['args'][0]['instId'] == 'BTCUSDT'

    def test_builds_login_message(self) -> None:
        client = BitgetWebSocketClient(MarketType.PERPETUAL, api_key='key', api_secret='secret', passphrase='pass', private=True)
        payload = client.build_login_message('1700000000000')
        assert payload['op'] == 'login'
        assert payload['args'][0]['apiKey'] == 'key'
        assert payload['args'][0]['passphrase'] == 'pass'
        assert payload['args'][0]['sign']

    def test_parses_books_channel(self) -> None:
        client = BitgetWebSocketClient(MarketType.SPOT)
        events = client.parse_message({'arg': {'instType': 'SPOT', 'channel': 'books', 'instId': 'BTCUSDT'}, 'data': [{'bids': [['100.0', '1']], 'asks': [['101.0', '2']], 'ts': '1700000000000'}]})
        assert events[0].channel == 'orderbook.update'
        assert events[0].payload['symbol'] == 'BTC/USDT'

    def test_parses_ticker_and_funding_messages(self) -> None:
        client = BitgetWebSocketClient(MarketType.PERPETUAL)
        events = client.parse_message({'arg': {'instType': 'USDT-FUTURES', 'channel': 'ticker', 'instId': 'BTCUSDT'}, 'data': [{'instId': 'BTCUSDT', 'bidPr': '100.0', 'askPr': '101.0', 'lastPr': '100.5', 'fundingRate': '0.0001', 'nextFundingTime': '1700003600000', 'markPrice': '100.4'}]})
        assert events[0].channel == 'ticker.update'
        assert events[0].payload['last'] == Decimal('100.5')
        assert events[1].channel == 'funding.update'
        assert events[1].payload['funding_rate'] == Decimal('0.0001')
