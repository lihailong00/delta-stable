from __future__ import annotations

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arb.net.errors import HttpStatusError, NetworkError
from arb.net.http import AsyncRateLimiter, HttpTransport


class _Response:
    def __init__(self, status_code: int, payload: dict[str, object], text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self) -> dict[str, object]:
        return self._payload


class _Client:
    def __init__(self, responses) -> None:
        self.responses = list(responses)
        self.calls = []

    async def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class HttpTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_retries_on_network_error(self) -> None:
        client = _Client([RuntimeError("boom"), _Response(200, {"ok": True})])
        transport = HttpTransport(client=client, retries=2)
        payload = await transport.request({"method": "GET", "url": "https://example.com"})
        self.assertEqual(payload["ok"], True)
        self.assertEqual(len(client.calls), 2)

    async def test_http_retries_on_5xx_then_raises_on_4xx(self) -> None:
        client = _Client([_Response(503, {}, "retry"), _Response(400, {}, "bad request")])
        transport = HttpTransport(client=client, retries=2)
        with self.assertRaises(HttpStatusError) as ctx:
            await transport.request({"method": "GET", "url": "https://example.com"})
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(len(client.calls), 2)

    async def test_rate_limiter_waits_before_next_request(self) -> None:
        clock = {"now": 0.0}
        sleeps: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)
            clock["now"] += seconds

        limiter = AsyncRateLimiter(requests_per_second=2, clock=lambda: clock["now"], sleep=fake_sleep)
        client = _Client([_Response(200, {"one": 1}), _Response(200, {"two": 2})])
        transport = HttpTransport(client=client, rate_limiter=limiter)
        await transport.request({"method": "GET", "url": "https://example.com/1"})
        await transport.request({"method": "GET", "url": "https://example.com/2"})
        self.assertEqual(sleeps, [0.5])


if __name__ == "__main__":
    unittest.main()
