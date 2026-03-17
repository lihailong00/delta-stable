"""离线示例：用 live runtime 跑 smoke 检查。

运行：
PYTHONPATH=src uv run python examples/runtime_smoke.py
"""

from __future__ import annotations

import asyncio

from arb.net.http import HttpTransport
from arb.runtime import BinanceRuntime, SmokeRunner


class _Response:
    def __init__(self, payload: dict) -> None:
        self.status_code = 200
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class _FakeHttpClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def request(self, method: str, url: str, **kwargs) -> _Response:
        self.calls.append((method, url))
        if url.endswith("/api/v3/ping"):
            return _Response({})
        if url.endswith("/api/v3/account"):
            return _Response(
                {
                    "balances": [
                        {"asset": "USDT", "free": "1000.0", "locked": "25.0"},
                        {"asset": "BTC", "free": "0.10", "locked": "0.00"},
                    ]
                }
            )
        raise RuntimeError(f"unexpected url: {url}")


async def main() -> None:
    runtime = BinanceRuntime.build(
        api_key="demo-key",
        api_secret="demo-secret",
        http_transport=HttpTransport(client=_FakeHttpClient()),
        ws_connector=lambda endpoint: None,
    )
    runner = SmokeRunner({"binance": runtime})
    results = await runner.run_many(["binance"], private=True)
    for line in runner.summarize(results):
        print(line)


if __name__ == "__main__":
    asyncio.run(main())
