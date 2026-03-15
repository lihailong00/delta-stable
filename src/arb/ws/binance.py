"""Binance WebSocket adapter."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from arb.models import MarketType
from arb.utils.symbols import exchange_symbol, normalize_symbol
from arb.ws.base import BaseWebSocketClient, WsEvent


class BinanceWebSocketClient(BaseWebSocketClient):
    """Binance spot and futures market-data WS adapter."""

    spot_endpoint = "wss://stream.binance.com:9443/ws"
    futures_endpoint = "wss://fstream.binance.com/ws"

    def __init__(self, market_type: MarketType = MarketType.SPOT) -> None:
        endpoint = self.spot_endpoint if market_type is MarketType.SPOT else self.futures_endpoint
        super().__init__("binance", endpoint, heartbeat_interval=20)
        self.market_type = market_type
        self._request_id = 0

    def build_subscribe_message(
        self,
        channel: str,
        *,
        symbol: str | None = None,
        market: str | None = None,
    ) -> Mapping[str, Any]:
        if symbol is None:
            raise ValueError("symbol is required for Binance subscriptions")
        self._request_id += 1
        return {
            "method": "SUBSCRIBE",
            "params": [self.stream_name(channel, symbol)],
            "id": self._request_id,
        }

    def stream_name(self, channel: str, symbol: str) -> str:
        exchange_name = exchange_symbol(symbol, delimiter="").lower()
        if channel == "bookTicker":
            return f"{exchange_name}@bookTicker"
        if channel == "depth":
            return f"{exchange_name}@depth"
        if channel == "markPrice":
            return f"{exchange_name}@markPrice@1s"
        raise ValueError(f"unsupported Binance WS channel: {channel}")

    def parse_message(self, message: Mapping[str, Any]) -> list[WsEvent]:
        payload = message.get("data", message)
        if not isinstance(payload, Mapping):
            return []
        if "result" in payload:
            return []
        event_type = payload.get("e")
        if event_type == "depthUpdate":
            return [self._parse_depth_update(payload)]
        if event_type == "markPriceUpdate":
            return [self._parse_mark_price(payload)]
        if {"s", "b", "B", "a", "A"}.issubset(payload.keys()):
            return [self._parse_book_ticker(payload)]
        return []

    def _parse_book_ticker(self, payload: Mapping[str, Any]) -> WsEvent:
        symbol = normalize_symbol(str(payload["s"]))
        return WsEvent(
            exchange=self.exchange,
            channel="orderbook.ticker",
            payload={
                "symbol": symbol,
                "best_bid": Decimal(str(payload["b"])),
                "bid_qty": Decimal(str(payload["B"])),
                "best_ask": Decimal(str(payload["a"])),
                "ask_qty": Decimal(str(payload["A"])),
            },
        )

    def _parse_depth_update(self, payload: Mapping[str, Any]) -> WsEvent:
        symbol = normalize_symbol(str(payload["s"]))
        return WsEvent(
            exchange=self.exchange,
            channel="orderbook.update",
            payload={
                "symbol": symbol,
                "first_update_id": int(payload["U"]),
                "final_update_id": int(payload["u"]),
                "bids": tuple((Decimal(str(price)), Decimal(str(size))) for price, size in payload.get("b", [])),
                "asks": tuple((Decimal(str(price)), Decimal(str(size))) for price, size in payload.get("a", [])),
            },
        )

    def _parse_mark_price(self, payload: Mapping[str, Any]) -> WsEvent:
        symbol = normalize_symbol(str(payload["s"]))
        return WsEvent(
            exchange=self.exchange,
            channel="funding.update",
            payload={
                "symbol": symbol,
                "mark_price": Decimal(str(payload["p"])),
                "index_price": Decimal(str(payload["i"])),
                "funding_rate": Decimal(str(payload["r"])),
                "next_funding_time": int(payload["T"]),
            },
        )
