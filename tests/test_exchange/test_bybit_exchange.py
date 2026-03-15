from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
import unittest
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arb.exchange.bybit import BybitExchange
from arb.models import MarketType, OrderStatus


class BybitExchangeTests(unittest.IsolatedAsyncioTestCase):
    async def test_sign_request_builds_bybit_headers(self) -> None:
        client = BybitExchange("key", "secret", transport=AsyncMock())
        headers = client.sign_request(
            "GET",
            "/v5/order/realtime",
            query="category=spot&symbol=BTCUSDT",
            timestamp="1658384314791",
        )
        self.assertEqual(headers["X-BAPI-API-KEY"], "key")
        self.assertEqual(headers["X-BAPI-TIMESTAMP"], "1658384314791")
        self.assertEqual(headers["X-BAPI-RECV-WINDOW"], "5000")
        self.assertTrue(headers["X-BAPI-SIGN"])

    async def test_fetch_ticker_uses_v5_market_tickers(self) -> None:
        transport = AsyncMock(
            return_value={
                "retCode": 0,
                "result": {
                    "list": [
                        {
                            "symbol": "BTCUSDT",
                            "bid1Price": "100.0",
                            "ask1Price": "101.0",
                            "lastPrice": "100.5",
                        }
                    ]
                },
            }
        )
        client = BybitExchange("key", "secret", transport=transport)
        ticker = await client.fetch_ticker("BTC/USDT", MarketType.SPOT)

        request = transport.await_args.args[0]
        self.assertEqual(request["path"], "/v5/market/tickers")
        self.assertEqual(request["params"]["category"], "spot")
        self.assertEqual(request["params"]["symbol"], "BTCUSDT")
        self.assertEqual(ticker.symbol, "BTC/USDT")
        self.assertEqual(ticker.last, Decimal("100.5"))

    async def test_build_ws_auth_message(self) -> None:
        client = BybitExchange("key", "secret", transport=AsyncMock())
        payload = client.build_ws_auth_message(1662350400000)
        self.assertEqual(payload["op"], "auth")
        self.assertEqual(payload["args"][0], "key")
        self.assertEqual(payload["args"][1], 1662350400000)
        self.assertTrue(payload["args"][2])

    async def test_create_order_uses_private_endpoint(self) -> None:
        transport = AsyncMock(return_value={"retCode": 0, "result": {"orderId": "abc123"}})
        client = BybitExchange("key", "secret", transport=transport)
        order = await client.create_order(
            "BTC/USDT",
            MarketType.PERPETUAL,
            "sell",
            Decimal("1"),
            price=Decimal("101"),
            reduce_only=True,
        )

        request = transport.await_args.args[0]
        self.assertEqual(request["path"], "/v5/order/create")
        self.assertTrue(request["signed"])
        self.assertEqual(request["body"]["category"], "linear")
        self.assertEqual(request["body"]["symbol"], "BTCUSDT")
        self.assertEqual(order.status, OrderStatus.NEW)
        self.assertEqual(order.order_id, "abc123")


if __name__ == "__main__":
    unittest.main()
