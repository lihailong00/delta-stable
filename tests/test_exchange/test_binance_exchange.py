from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
import unittest
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arb.exchange.binance import BinanceExchange
from arb.models import MarketType, OrderStatus


class BinanceExchangeTests(unittest.IsolatedAsyncioTestCase):
    async def test_sign_params_matches_expected_hmac(self) -> None:
        client = BinanceExchange(
            "vmPUZE6mv9SD5VNHk4HlWFsOr6aKE2zvsw0MuIgwCIPy6utIco14y7Ju91duEh8A",
            "NhqPtmdSJYdKjVHjA7PZj4Mge3R5YNiP1e3UZjInClVN65XAbvqqM6A7H5fATj0j",
            transport=AsyncMock(),
        )
        params = {
            "symbol": "LTCBTC",
            "side": "BUY",
            "type": "LIMIT",
            "timeInForce": "GTC",
            "quantity": "1",
            "price": "0.1",
            "recvWindow": "5000",
        }
        signed = client.sign_params(params, timestamp=1499827319559)
        self.assertEqual(
            signed["signature"],
            "c8db56825ae71d6d79447849e617115f4a920fa2acdcab2b053c4b2838bd6b71",
        )

    async def test_fetch_ticker_uses_book_ticker_endpoint(self) -> None:
        transport = AsyncMock(
            return_value={
                "symbol": "BTCUSDT",
                "bidPrice": "100.0",
                "bidQty": "1.0",
                "askPrice": "101.0",
                "askQty": "2.0",
            }
        )
        client = BinanceExchange("key", "secret", transport=transport)
        ticker = await client.fetch_ticker("BTC/USDT", MarketType.SPOT)

        request = transport.await_args.args[0]
        self.assertEqual(request["path"], "/api/v3/ticker/bookTicker")
        self.assertEqual(request["params"]["symbol"], "BTCUSDT")
        self.assertEqual(ticker.symbol, "BTC/USDT")
        self.assertEqual(ticker.bid, Decimal("100.0"))
        self.assertEqual(ticker.ask, Decimal("101.0"))

    async def test_fetch_funding_rate_uses_premium_index(self) -> None:
        transport = AsyncMock(
            return_value={
                "symbol": "BTCUSDT",
                "markPrice": "11793.63104562",
                "indexPrice": "11781.80495970",
                "lastFundingRate": "0.00038246",
                "nextFundingTime": 1597392000000,
            }
        )
        client = BinanceExchange("key", "secret", transport=transport)
        funding = await client.fetch_funding_rate("BTC/USDT")

        request = transport.await_args.args[0]
        self.assertEqual(request["path"], "/fapi/v1/premiumIndex")
        self.assertEqual(funding.symbol, "BTC/USDT")
        self.assertEqual(funding.rate, Decimal("0.00038246"))

    async def test_create_order_signs_private_requests(self) -> None:
        transport = AsyncMock(
            return_value={
                "symbol": "BTCUSDT",
                "side": "SELL",
                "origQty": "1",
                "executedQty": "0",
                "price": "101",
                "status": "NEW",
                "orderId": 12345,
                "avgPrice": "0",
            }
        )
        client = BinanceExchange("key", "secret", transport=transport)
        order = await client.create_order(
            "BTC/USDT",
            MarketType.PERPETUAL,
            "sell",
            Decimal("1"),
            price=Decimal("101"),
            reduce_only=True,
        )

        request = transport.await_args.args[0]
        self.assertEqual(request["path"], "/fapi/v1/order")
        self.assertTrue(request["signed"])
        self.assertEqual(request["headers"]["X-MBX-APIKEY"], "key")
        self.assertIn("signature", request["params"])
        self.assertEqual(order.status, OrderStatus.NEW)
        self.assertEqual(order.order_id, "12345")


if __name__ == "__main__":
    unittest.main()
