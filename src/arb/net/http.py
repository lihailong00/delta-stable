"""Async HTTP transport wrapper."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from arb.net.errors import HttpStatusError, NetworkError

try:
    import httpx  # type: ignore
except Exception:  # pragma: no cover
    httpx = None  # type: ignore

Signer = Callable[[dict[str, Any]], dict[str, Any]]
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
        client: Any | None = None,
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

    async def request(self, request: Mapping[str, Any]) -> Any:
        payload = dict(request)
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

    async def _send(self, request: Mapping[str, Any]) -> Any:
        try:
            response = await self.client.request(
                request["method"],
                request["url"],
                headers=request.get("headers"),
                params=request.get("params"),
                json=request.get("body") or request.get("json"),
                content=request.get("body_text"),
                timeout=request.get("timeout", self.timeout),
            )
        except Exception as exc:  # pragma: no cover - exercised via fake client in tests
            raise NetworkError(str(exc)) from exc

        status_code = getattr(response, "status_code", 200)
        if status_code >= 400:
            raise HttpStatusError(status_code, getattr(response, "text", ""))

        if hasattr(response, "json"):
            return response.json()
        return response

    @staticmethod
    def _build_default_client(timeout: float) -> Any:
        if httpx is None:
            raise RuntimeError("httpx is not installed; inject a client or install httpx")
        return httpx.AsyncClient(timeout=timeout)
