from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
import unittest
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arb.exchange.gate import GateExchange
from arb.models import MarketType, OrderStatus


class GateExchangeTests(unittest.IsolatedAsyncioTestCase):
    async def test_sign_request_uses_gate_signature_payload(self) -> None:
        client = GateExchange("key", "secret", transport=AsyncMock())
        headers = client.sign_request(
            "GET",
            "/spot/accounts",
            query="currency=BTC",
            body="",
            timestamp="1684372832",
        )
        self.assertEqual(headers["KEY"], "key")
        self.assertEqual(headers["Timestamp"], "1684372832")
        self.assertTrue(headers["SIGN"])

    async def test_fetch_ticker_uses_spot_endpoint(self) -> None:
        transport = AsyncMock(
            return_value=[
                {
                    "currency_pair": "BTC_USDT",
                    "last": "100.5",
                    "lowest_ask": "101.0",
                    "highest_bid": "100.0",
                }
            ]
        )
        client = GateExchange("key", "secret", transport=transport)
        ticker = await client.fetch_ticker("BTC/USDT", MarketType.SPOT)

        request = transport.await_args.args[0]
        self.assertEqual(request["path"], "/spot/tickers")
        self.assertEqual(request["params"]["currency_pair"], "BTC_USDT")
        self.assertEqual(ticker.symbol, "BTC/USDT")
        self.assertEqual(ticker.ask, Decimal("101.0"))

    async def test_create_order_signs_gate_private_requests(self) -> None:
        transport = AsyncMock(return_value={"id": "123456"})
        client = GateExchange("key", "secret", transport=transport)
        order = await client.create_order(
            "BTC/USDT",
            MarketType.SPOT,
            "sell",
            Decimal("1"),
            price=Decimal("101"),
        )

        request = transport.await_args.args[0]
        self.assertEqual(request["path"], "/spot/orders")
        self.assertTrue(request["signed"])
        self.assertEqual(request["body"]["currency_pair"], "BTC_USDT")
        self.assertEqual(order.status, OrderStatus.NEW)
        self.assertEqual(order.order_id, "123456")

    async def test_symbol_conversion_round_trip(self) -> None:
        client = GateExchange("key", "secret", transport=AsyncMock())
        self.assertEqual(client.to_exchange_symbol("BTC/USDT"), "BTC_USDT")
        self.assertEqual(client.from_exchange_symbol("BTC_USDT"), "BTC/USDT")


if __name__ == "__main__":
    unittest.main()
