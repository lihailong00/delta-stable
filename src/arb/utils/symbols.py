"""Helpers for symbol normalization across exchanges."""

from __future__ import annotations


COMMON_QUOTES = ("USDT", "USDC", "USD", "BTC", "ETH", "EUR")


def normalize_symbol(symbol: str, known_quotes: tuple[str, ...] = COMMON_QUOTES) -> str:
    raw = symbol.strip().upper()
    if not raw:
        raise ValueError("symbol must not be empty")

    for delimiter in (":", "-", "_"):
        raw = raw.replace(delimiter, "/")

    if "/" in raw:
        base, quote = raw.split("/", 1)
        if not base or not quote:
            raise ValueError(f"invalid symbol: {symbol}")
        return f"{base}/{quote}"

    for quote in sorted(known_quotes, key=len, reverse=True):
        if raw.endswith(quote) and len(raw) > len(quote):
            return f"{raw[:-len(quote)]}/{quote}"

    raise ValueError(f"unable to infer quote asset from symbol: {symbol}")


def split_symbol(symbol: str) -> tuple[str, str]:
    normalized = normalize_symbol(symbol)
    base, quote = normalized.split("/", 1)
    return base, quote


def exchange_symbol(
    symbol: str,
    *,
    delimiter: str = "_",
    known_quotes: tuple[str, ...] = COMMON_QUOTES,
) -> str:
    base, quote = split_symbol(normalize_symbol(symbol, known_quotes=known_quotes))
    return f"{base}{delimiter}{quote}" if delimiter else f"{base}{quote}"
