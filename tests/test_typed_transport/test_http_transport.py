from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.asyncio

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from typed_transport.errors import HttpStatusError, NetworkError
from typed_transport.http import AsyncRateLimiter, HttpTransport


class _Response:
    def __init__(self, status_code: int, payload: dict[str, object], text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text or str(payload)
        self._bytes = self.text.encode("utf-8")

    def json(self) -> dict[str, object]:
        return self._payload

    def read(self) -> bytes:
        return self._bytes


class _Client:
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict[str, object]]] = []
        self.closed = False

    async def request(self, method: str, url: str, **kwargs: object) -> object:
        self.calls.append((method, url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    async def aclose(self) -> None:
        self.closed = True


class TestTypedHttpTransport:
    async def test_request_json_retries_on_network_error(self) -> None:
        client = _Client([RuntimeError("boom"), _Response(200, {"ok": True})])
        transport = HttpTransport(client=client, retries=2)

        payload = await transport.request_json({"method": "GET", "url": "https://example.com"})

        assert payload["ok"] is True
        assert len(client.calls) == 2

    async def test_request_text_and_bytes_use_raw_response(self) -> None:
        client = _Client([
            _Response(200, {"ok": True}, text="hello"),
            _Response(200, {"ok": True}, text="hello"),
        ])
        transport = HttpTransport(client=client, retries=0)

        text = await transport.request_text({"method": "GET", "url": "https://example.com"})
        binary = await transport.request_bytes({"method": "GET", "url": "https://example.com"})

        assert text == "hello"
        assert binary == b"hello"

    async def test_request_raw_raises_on_4xx(self) -> None:
        client = _Client([_Response(400, {}, "bad request")])
        transport = HttpTransport(client=client, retries=0)

        with pytest.raises(HttpStatusError):
            await transport.request_raw({"method": "GET", "url": "https://example.com"})

    async def test_rate_limiter_waits_between_requests(self) -> None:
        clock = {"now": 0.0}
        sleeps: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)
            clock["now"] += seconds

        limiter = AsyncRateLimiter(
            requests_per_second=2,
            clock=lambda: clock["now"],
            sleep=fake_sleep,
        )
        client = _Client([_Response(200, {"one": 1}), _Response(200, {"two": 2})])
        transport = HttpTransport(client=client, rate_limiter=limiter)

        await transport.request({"method": "GET", "url": "https://example.com/1"})
        await transport.request({"method": "GET", "url": "https://example.com/2"})

        assert sleeps == [0.5]

    async def test_aclose_forwards_to_underlying_client(self) -> None:
        client = _Client([_Response(200, {"ok": True})])
        transport = HttpTransport(client=client)

        await transport.aclose()

        assert client.closed
