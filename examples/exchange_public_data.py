"""离线示例：用假的 REST transport 调交易所适配器。

运行：
PYTHONPATH=src uv run python examples/exchange_public_data.py
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from arb.exchange.binance import BinanceExchange
from arb.models import MarketType


async def fake_transport(request: dict[str, Any]) -> dict[str, Any]:
    path = request["path"]
    params = request.get("params", {})
    symbol = params.get("symbol", "BTCUSDT")
    if path.endswith("bookTicker"):
        return {
            "symbol": symbol,
            "bidPrice": "101000.0",
            "askPrice": "101010.0",
            "bidQty": "2.5",
            "askQty": "3.0",
        }
    if path.endswith("depth"):
        return {
            "lastUpdateId": 1,
            "bids": [["101000.0", "2.5"], ["100999.5", "3.1"]],
            "asks": [["101010.0", "3.0"], ["101011.0", "4.2"]],
        }
    if path.endswith("premiumIndex"):
        return {
            "symbol": symbol,
            "lastFundingRate": "0.00045",
            "nextFundingTime": 1767225600000,
        }
    raise RuntimeError(f"unexpected request: {request}")


async def main() -> None:
    exchange = BinanceExchange("demo-key", "demo-secret", transport=fake_transport)
    ticker = await exchange.fetch_ticker("BTC/USDT", MarketType.SPOT)
    orderbook = await exchange.fetch_orderbook("BTC/USDT", MarketType.SPOT)
    funding = await exchange.fetch_funding_rate("BTC/USDT")

    print("ticker")
    print(json.dumps(ticker.to_dict(), indent=2, default=str))
    print("orderbook")
    print(json.dumps(orderbook.to_dict(), indent=2, default=str))
    print("funding")
    print(json.dumps(funding.to_dict(), indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
