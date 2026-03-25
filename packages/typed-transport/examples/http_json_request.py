from __future__ import annotations

import asyncio

from typed_transport import HttpTransport


class _Response:
    def __init__(self, payload: dict[str, object]) -> None:
        self.status_code = 200
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict[str, object]:
        return self._payload

    def read(self) -> bytes:
        return self.text.encode("utf-8")


class _Client:
    async def request(self, method: str, url: str, **kwargs: object) -> _Response:
        return _Response(
            {
                "method": method,
                "url": url,
                "timeout": kwargs.get("timeout"),
                "headers": kwargs.get("headers") or {},
            }
        )

    async def aclose(self) -> None:
        return None


async def main() -> None:
    transport = HttpTransport(client=_Client())
    payload = await transport.request_json(
        {
            "method": "GET",
            "url": "https://example.com/api/ping",
            "headers": {"X-Demo": "typed-transport"},
        }
    )
    print(payload)
    await transport.aclose()


if __name__ == "__main__":
    asyncio.run(main())
