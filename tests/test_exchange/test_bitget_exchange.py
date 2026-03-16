from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
import unittest
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arb.exchange.bitget import BitgetExchange
from arb.models import MarketType, OrderStatus


class BitgetExchangeTests(unittest.IsolatedAsyncioTestCase):
    async def test_sign_request_builds_bitget_headers(self) -> None:
        client = BitgetExchange("key", "secret", "pass", transport=AsyncMock())
        headers = client.sign_request(
            "GET",
            "/api/v2/spot/account/assets",
            query="coin=USDT",
            timestamp="1700000000000",
        )
        self.assertEqual(headers["ACCESS-KEY"], "key")
        self.assertEqual(headers["ACCESS-PASSPHRASE"], "pass")
        self.assertEqual(headers["ACCESS-TIMESTAMP"], "1700000000000")
        self.assertTrue(headers["ACCESS-SIGN"])

    async def test_fetch_ticker_uses_spot_tickers_endpoint(self) -> None:
        transport = AsyncMock(
            return_value={
                "code": "00000",
                "data": [
                    {
                        "symbol": "BTCUSDT",
                        "bidPr": "100.0",
                        "askPr": "101.0",
                        "lastPr": "100.5",
                    }
                ],
            }
        )
        client = BitgetExchange("key", "secret", "pass", transport=transport)
        ticker = await client.fetch_ticker("BTC/USDT", MarketType.SPOT)

        request = transport.await_args.args[0]
        self.assertEqual(request["path"], "/api/v2/spot/market/tickers")
        self.assertEqual(request["params"]["symbol"], "BTCUSDT")
        self.assertEqual(ticker.symbol, "BTC/USDT")
        self.assertEqual(ticker.bid, Decimal("100.0"))

    async def test_create_order_uses_mix_order_endpoint(self) -> None:
        transport = AsyncMock(return_value={"code": "00000", "data": {"orderId": "12345"}})
        client = BitgetExchange("key", "secret", "pass", transport=transport)
        order = await client.create_order(
            "BTC/USDT",
            MarketType.PERPETUAL,
            "sell",
            Decimal("1"),
            price=Decimal("101"),
            reduce_only=True,
        )

        request = transport.await_args.args[0]
        self.assertEqual(request["path"], "/api/v2/mix/order/place-order")
        self.assertTrue(request["signed"])
        self.assertEqual(request["body"]["symbol"], "BTCUSDT")
        self.assertEqual(request["body"]["tradeSide"], "close")
        self.assertEqual(order.status, OrderStatus.NEW)
        self.assertEqual(order.order_id, "12345")


if __name__ == "__main__":
    unittest.main()
