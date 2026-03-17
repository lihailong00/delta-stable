"""Helpers for normalizing funding settlement intervals."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

DEFAULT_FUNDING_INTERVAL_HOURS = 8

_HOUR_KEYS = (
    "funding_interval_hours",
    "fundingIntervalHours",
    "fundingIntervalHour",
    "funding_interval",
    "fundingInterval",
    "fundInterval",
)
_MINUTE_KEYS = (
    "funding_interval_minutes",
    "fundingIntervalMinutes",
)
_SECOND_KEYS = (
    "funding_interval_seconds",
    "fundingIntervalSeconds",
)
_MILLISECOND_KEYS = (
    "funding_interval_ms",
    "fundingIntervalMs",
)


def normalize_funding_interval_hours(
    value: object | None,
    *,
    default: int = DEFAULT_FUNDING_INTERVAL_HOURS,
) -> int:
    """Normalize interval values from exchange payloads into hours."""

    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, Decimal):
        interval_hours = int(value)
        return interval_hours if interval_hours > 0 else default
    if isinstance(value, int):
        return value if value > 0 else default
    if isinstance(value, float):
        interval_hours = int(value)
        return interval_hours if interval_hours > 0 else default
    if not isinstance(value, str):
        return default

    text = value.strip().lower()
    if not text:
        return default
    if text.endswith("ms"):
        interval_hours = int(text[:-2].strip()) // (60 * 60 * 1000)
        return max(interval_hours, 1)
    if text.endswith("sec"):
        interval_hours = int(text[:-3].strip()) // 3600
        return max(interval_hours, 1)
    if text.endswith("s"):
        interval_hours = int(text[:-1].strip()) // 3600
        return max(interval_hours, 1)
    if text.endswith("min"):
        interval_hours = int(text[:-3].strip()) // 60
        return max(interval_hours, 1)
    if text.endswith("m"):
        interval_hours = int(text[:-1].strip()) // 60
        return max(interval_hours, 1)
    if text.endswith("hours"):
        interval_hours = int(text[:-5].strip())
        return interval_hours if interval_hours > 0 else default
    if text.endswith("hour"):
        interval_hours = int(text[:-4].strip())
        return interval_hours if interval_hours > 0 else default
    if text.endswith("hr"):
        interval_hours = int(text[:-2].strip())
        return interval_hours if interval_hours > 0 else default
    if text.endswith("h"):
        interval_hours = int(text[:-1].strip())
        return interval_hours if interval_hours > 0 else default
    interval_hours = int(text)
    return interval_hours if interval_hours > 0 else default


def extract_funding_interval_hours(
    payload: Mapping[str, object],
    *,
    default: int = DEFAULT_FUNDING_INTERVAL_HOURS,
) -> int:
    """Extract interval hours from common funding payload field names."""

    for key in _HOUR_KEYS:
        value = payload.get(key)
        if value not in (None, ""):
            return normalize_funding_interval_hours(value, default=default)
    for key in _MINUTE_KEYS:
        value = payload.get(key)
        if value not in (None, ""):
            return normalize_funding_interval_hours(f"{value}m", default=default)
    for key in _SECOND_KEYS:
        value = payload.get(key)
        if value not in (None, ""):
            return normalize_funding_interval_hours(f"{value}s", default=default)
    for key in _MILLISECOND_KEYS:
        value = payload.get(key)
        if value not in (None, ""):
            return normalize_funding_interval_hours(f"{value}ms", default=default)
    return default
