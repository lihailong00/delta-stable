"""Async HTTP transport wrapper."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Protocol, cast

from .errors import HttpStatusError, NetworkError
from .types import HttpRequest, JsonValue, coerce_http_request

try:
    import httpx  # type: ignore
except Exception:  # pragma: no cover
    httpx = None  # type: ignore


class SupportsHttpResponse(Protocol):
    status_code: int
    text: str

    def json(self) -> object:
        """Return a decoded JSON payload."""

    def read(self) -> bytes:
        """Return raw bytes."""


class SupportsHttpClient(Protocol):
    async def request(self, method: str, url: str, **kwargs: object) -> object:
        """Execute one HTTP request."""

    async def aclose(self) -> None:
        """Close the underlying client."""


Signer = Callable[[HttpRequest], HttpRequest]
SleepFn = Callable[[float], Awaitable[None]]
ClockFn = Callable[[], float]


class AsyncRateLimiter:
    """Simple per-second request rate limiter."""

    def __init__(
        self,
        *,
        requests_per_second: float,
        clock: ClockFn | None = None,
        sleep: SleepFn | None = None,
    ) -> None:
        self.requests_per_second = requests_per_second
        self.clock = clock or time.monotonic
        self.sleep = sleep or asyncio.sleep
        self._next_available_at = 0.0

    async def acquire(self) -> None:
        now = self.clock()
        wait_seconds = self._next_available_at - now
        if wait_seconds > 0:
            await self.sleep(wait_seconds)
            now = self.clock()
        interval = 1 / self.requests_per_second if self.requests_per_second > 0 else 0
        self._next_available_at = max(self._next_available_at, now) + interval


class HttpTransport:
    """Thin async HTTP wrapper with retries, timeout and optional signing."""

    def __init__(
        self,
        *,
        client: SupportsHttpClient | None = None,
        timeout: float = 10.0,
        retries: int = 2,
        rate_limiter: AsyncRateLimiter | None = None,
        signer: Signer | None = None,
        sleep: SleepFn | None = None,
    ) -> None:
        self.timeout = timeout
        self.retries = retries
        self.rate_limiter = rate_limiter
        self.signer = signer
        self.sleep = sleep or asyncio.sleep
        self.client = client or self._build_default_client(timeout)

    async def request(self, request: HttpRequest | Mapping[str, JsonValue]) -> JsonValue:
        return await self.request_json(request)

    async def request_json(self, request: HttpRequest | Mapping[str, JsonValue]) -> JsonValue:
        response = await self.request_raw(request)
        if hasattr(response, "json"):
            payload = cast(SupportsHttpResponse, response).json()
            return cast(JsonValue, payload)
        raise TypeError("request_json expected a JSON-capable response")

    async def request_text(self, request: HttpRequest | Mapping[str, JsonValue]) -> str:
        response = await self.request_raw(request)
        return getattr(response, "text", "")

    async def request_bytes(self, request: HttpRequest | Mapping[str, JsonValue]) -> bytes:
        response = await self.request_raw(request)
        if hasattr(response, "read"):
            return cast(SupportsHttpResponse, response).read()
        return bytes(str(response), "utf-8")  # pragma: no cover

    async def request_raw(self, request: HttpRequest | Mapping[str, JsonValue]) -> object:
        payload = coerce_http_request(request)
        if self.signer is not None:
            payload = self.signer(payload)
        if self.rate_limiter is not None:
            await self.rate_limiter.acquire()

        attempts = 0
        while True:
            attempts += 1
            try:
                return await self._send(payload)
            except HttpStatusError as exc:
                if exc.status_code < 500 or attempts > self.retries:
                    raise
            except NetworkError:
                if attempts > self.retries:
                    raise
            await self.sleep(min(0.05 * attempts, 0.2))

    async def aclose(self) -> None:
        if hasattr(self.client, "aclose"):
            await self.client.aclose()

    async def _send(self, request: HttpRequest) -> object:
        try:
            response = await self.client.request(
                request.method,
                request.url,
                headers=request.headers or None,
                params=request.params or None,
                json=request.json_body,
                content=request.body_text,
                timeout=request.timeout or self.timeout,
            )
        except Exception as exc:  # pragma: no cover - exercised via fake client in tests
            raise NetworkError(str(exc)) from exc

        status_code = getattr(response, "status_code", 200)
        if status_code >= 400:
            raise HttpStatusError(status_code, getattr(response, "text", ""))
        return response

    @staticmethod
    def _build_default_client(timeout: float) -> SupportsHttpClient:
        if httpx is None:
            raise RuntimeError("httpx is not installed; inject a client or install httpx")
        return cast(SupportsHttpClient, httpx.AsyncClient(timeout=timeout))
