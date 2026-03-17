"""Live 示例：对真实 Binance 账户做 smoke 检查。

运行前设置：
export BINANCE_API_KEY=...
export BINANCE_API_SECRET=...

运行：
PYTHONPATH=src uv run python examples/live_binance_smoke.py
"""

from __future__ import annotations

import asyncio
import os

from arb.net.http import HttpTransport
from arb.runtime import BinanceRuntime, SmokeRunner


async def main() -> None:
    api_key = os.environ.get("BINANCE_API_KEY")
    api_secret = os.environ.get("BINANCE_API_SECRET")
    if not api_key or not api_secret:
        raise SystemExit("missing BINANCE_API_KEY or BINANCE_API_SECRET")

    runtime = BinanceRuntime.build(
        api_key=api_key,
        api_secret=api_secret,
        http_transport=HttpTransport(),
        ws_connector=lambda endpoint: None,
    )
    runner = SmokeRunner({"binance": runtime})
    results = await runner.run_many(["binance"], private=True)
    for line in runner.summarize(results):
        print(line)


if __name__ == "__main__":
    asyncio.run(main())
