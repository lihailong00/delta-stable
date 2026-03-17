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

    def __init__(
        self,
        market_type: MarketType = MarketType.SPOT,
        *,
        private: bool = False,
        listen_key: str | None = None,
    ) -> None:
        endpoint = self.spot_endpoint if market_type is MarketType.SPOT else self.futures_endpoint
        super().__init__("binance", endpoint, heartbeat_interval=20)
        self.market_type = market_type
        self.private = private
        self.listen_key = listen_key
        self._request_id = 0

    def build_subscribe_message(
        self,
        channel: str,
        *,
        symbol: str | None = None,
        market: str | None = None,
    ) -> Mapping[str, Any]:
        if self.private:
            if channel not in {"orders", "positions", "fills", "userData"}:
                raise ValueError(f"unsupported Binance private channel: {channel}")
            self._request_id += 1
            return {
                "method": "SUBSCRIBE",
                "params": [self.listen_key or channel],
                "id": self._request_id,
            }
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
        if event_type == "executionReport":
            return self._parse_execution_report(payload)
        if event_type == "ACCOUNT_UPDATE":
            return self._parse_account_update(payload)
        if event_type == "ORDER_TRADE_UPDATE":
            return self._parse_futures_order_update(payload)
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

    def _parse_execution_report(self, payload: Mapping[str, Any]) -> list[WsEvent]:
        symbol = normalize_symbol(str(payload["s"]))
        events = [
            WsEvent(
                exchange=self.exchange,
                channel="order.update",
                payload={
                    "symbol": symbol,
                    "order_id": str(payload["i"]),
                    "side": str(payload["S"]).lower(),
                    "status": str(payload["X"]).lower(),
                    "quantity": Decimal(str(payload["q"])),
                    "filled_quantity": Decimal(str(payload.get("z", "0"))),
                    "price": Decimal(str(payload["p"])) if payload.get("p") not in (None, "", "0") else None,
                },
            )
        ]
        last_fill = Decimal(str(payload.get("l", "0")))
        if last_fill > 0:
            events.append(
                WsEvent(
                    exchange=self.exchange,
                    channel="fill.update",
                    payload={
                        "symbol": symbol,
                        "order_id": str(payload["i"]),
                        "fill_id": str(payload.get("t", "")),
                        "side": str(payload["S"]).lower(),
                        "quantity": last_fill,
                        "price": Decimal(str(payload.get("L", payload.get("p", "0")))),
                        "fee": Decimal(str(payload.get("n", "0"))),
                        "fee_asset": payload.get("N"),
                    },
                )
            )
        return events

    def _parse_account_update(self, payload: Mapping[str, Any]) -> list[WsEvent]:
        account = payload.get("a", {})
        positions = []
        for item in account.get("P", []):
            quantity = Decimal(str(item.get("pa", "0")))
            if quantity == 0:
                continue
            positions.append(
                WsEvent(
                    exchange=self.exchange,
                    channel="position.update",
                    payload={
                        "symbol": normalize_symbol(str(item["s"])),
                        "direction": "long" if quantity > 0 else "short",
                        "quantity": abs(quantity),
                        "entry_price": Decimal(str(item.get("ep", "0"))),
                        "mark_price": Decimal(str(item.get("mp", "0"))),
                        "unrealized_pnl": Decimal(str(item.get("up", "0"))),
                    },
                )
            )
        return positions

    def _parse_futures_order_update(self, payload: Mapping[str, Any]) -> list[WsEvent]:
        order = payload.get("o", {})
        symbol = normalize_symbol(str(order["s"]))
        events = [
            WsEvent(
                exchange=self.exchange,
                channel="order.update",
                payload={
                    "symbol": symbol,
                    "order_id": str(order["i"]),
                    "side": str(order["S"]).lower(),
                    "status": str(order["X"]).lower(),
                    "quantity": Decimal(str(order["q"])),
                    "filled_quantity": Decimal(str(order.get("z", "0"))),
                    "price": Decimal(str(order["p"])) if order.get("p") not in (None, "", "0") else None,
                },
            )
        ]
        last_fill = Decimal(str(order.get("l", "0")))
        if last_fill > 0:
            events.append(
                WsEvent(
                    exchange=self.exchange,
                    channel="fill.update",
                    payload={
                        "symbol": symbol,
                        "order_id": str(order["i"]),
                        "fill_id": str(order.get("t", "")),
                        "side": str(order["S"]).lower(),
                        "quantity": last_fill,
                        "price": Decimal(str(order.get("L", order.get("ap", "0")))),
                        "fee": Decimal(str(order.get("n", "0"))),
                        "fee_asset": order.get("N"),
                    },
                )
            )
        return events
