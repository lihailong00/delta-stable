from __future__ import annotations
import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from arb.utils.symbols import exchange_symbol, normalize_symbol, split_symbol

class TestSymbolUtils:

    def test_normalize_symbol_accepts_common_exchange_formats(self) -> None:
        assert normalize_symbol('btc_usdt') == 'BTC/USDT'
        assert normalize_symbol('BTC-USDT') == 'BTC/USDT'
        assert normalize_symbol('ETHUSDT') == 'ETH/USDT'

    def test_split_symbol_returns_base_and_quote(self) -> None:
        assert split_symbol('SOL/USDC') == ('SOL', 'USDC')

    def test_exchange_symbol_allows_custom_delimiters(self) -> None:
        assert exchange_symbol('BTC/USDT', delimiter='_') == 'BTC_USDT'
        assert exchange_symbol('BTCUSDT', delimiter='') == 'BTCUSDT'

    def test_invalid_symbol_raises(self) -> None:
        with pytest.raises(ValueError):
            normalize_symbol('')
