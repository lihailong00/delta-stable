from __future__ import annotations

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arb.utils.symbols import exchange_symbol, normalize_symbol, split_symbol


class SymbolUtilsTests(unittest.TestCase):
    def test_normalize_symbol_accepts_common_exchange_formats(self) -> None:
        self.assertEqual(normalize_symbol("btc_usdt"), "BTC/USDT")
        self.assertEqual(normalize_symbol("BTC-USDT"), "BTC/USDT")
        self.assertEqual(normalize_symbol("ETHUSDT"), "ETH/USDT")

    def test_split_symbol_returns_base_and_quote(self) -> None:
        self.assertEqual(split_symbol("SOL/USDC"), ("SOL", "USDC"))

    def test_exchange_symbol_allows_custom_delimiters(self) -> None:
        self.assertEqual(exchange_symbol("BTC/USDT", delimiter="_"), "BTC_USDT")
        self.assertEqual(exchange_symbol("BTCUSDT", delimiter=""), "BTCUSDT")

    def test_invalid_symbol_raises(self) -> None:
        with self.assertRaises(ValueError):
            normalize_symbol("")


if __name__ == "__main__":
    unittest.main()
