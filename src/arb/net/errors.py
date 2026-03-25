"""Compatibility re-exports for typed transport errors."""

from typed_transport.errors import HttpStatusError, NetworkError, RateLimitError, WebSocketClosedError

__all__ = [
    "HttpStatusError",
    "NetworkError",
    "RateLimitError",
    "WebSocketClosedError",
]
