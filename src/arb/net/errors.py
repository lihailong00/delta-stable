"""Network-layer exceptions."""


class NetworkError(Exception):
    """Base network error."""


class RateLimitError(NetworkError):
    """Raised when rate limiting prevents a request or subscription."""


class HttpStatusError(NetworkError):
    """Raised for unexpected HTTP status codes."""

    def __init__(self, status_code: int, message: str = "") -> None:
        self.status_code = status_code
        super().__init__(message or f"http status error: {status_code}")


class WebSocketClosedError(NetworkError):
    """Raised when a websocket session closes unexpectedly."""
