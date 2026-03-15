from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
import unittest
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arb.exchange.okx import OkxExchange
from arb.models import MarketType, OrderStatus


class OkxExchangeTests(unittest.IsolatedAsyncioTestCase):
    async def test_sign_request_builds_okx_headers(self) -> None:
        client = OkxExchange("key", "secret", "pass", transport=AsyncMock())
        headers = client.sign_request(
            "GET",
            "/api/v5/account/balance",
            query="ccy=BTC",
            timestamp="2020-12-08T09:08:57.715Z",
        )
        self.assertEqual(headers["OK-ACCESS-KEY"], "key")
        self.assertEqual(headers["OK-ACCESS-TIMESTAMP"], "2020-12-08T09:08:57.715Z")
        self.assertEqual(headers["OK-ACCESS-PASSPHRASE"], "pass")
        self.assertTrue(headers["OK-ACCESS-SIGN"])

    async def test_fetch_ticker_uses_inst_id_format(self) -> None:
        transport = AsyncMock(
            return_value={
                "code": "0",
                "data": [
                    {
                        "instId": "BTC-USDT",
                        "last": "100.5",
                        "bidPx": "100.0",
                        "askPx": "101.0",
                    }
                ],
            }
        )
        client = OkxExchange("key", "secret", "pass", transport=transport)
        ticker = await client.fetch_ticker("BTC/USDT", MarketType.SPOT)

        request = transport.await_args.args[0]
        self.assertEqual(request["path"], "/api/v5/market/ticker")
        self.assertEqual(request["params"]["instId"], "BTC-USDT")
        self.assertEqual(ticker.symbol, "BTC/USDT")
        self.assertEqual(ticker.bid, Decimal("100.0"))

    async def test_build_login_args_for_ws(self) -> None:
        client = OkxExchange("key", "secret", "pass", transport=AsyncMock())
        args = client.build_login_args("1704876947")
        self.assertEqual(args["apiKey"], "key")
        self.assertEqual(args["passphrase"], "pass")
        self.assertEqual(args["timestamp"], "1704876947")
        self.assertTrue(args["sign"])

    async def test_create_order_uses_trade_endpoint(self) -> None:
        transport = AsyncMock(return_value={"code": "0", "data": [{"ordId": "312269865356374016"}]})
        client = OkxExchange("key", "secret", "pass", transport=transport)
        order = await client.create_order(
            "BTC/USDT",
            MarketType.PERPETUAL,
            "sell",
            Decimal("1"),
            price=Decimal("101"),
            reduce_only=True,
        )

        request = transport.await_args.args[0]
        self.assertEqual(request["path"], "/api/v5/trade/order")
        self.assertTrue(request["signed"])
        self.assertEqual(request["body"]["instId"], "BTC-USDT-SWAP")
        self.assertEqual(order.status, OrderStatus.NEW)
        self.assertEqual(order.order_id, "312269865356374016")


if __name__ == "__main__":
    unittest.main()
