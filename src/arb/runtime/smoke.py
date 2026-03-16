"""Smoke checks for live exchange runtimes."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True, frozen=True)
class SmokeResult:
    exchange: str
    public_ok: bool
    private_ok: bool | None
    detail: str


class SmokeRunner:
    """Run public/private readiness checks against live runtimes."""

    def __init__(self, runtimes: dict[str, Any]) -> None:
        self.runtimes = dict(runtimes)

    async def run_exchange(self, exchange: str, *, private: bool = False) -> SmokeResult:
        runtime = self.runtimes[exchange]
        public_ok = False
        private_ok: bool | None = None
        detail = "ok"
        try:
            public_ok = bool(await runtime.public_ping())
        except Exception as exc:
            return SmokeResult(exchange, False, None, f"public ping failed: {exc}")

        if private:
            try:
                await runtime.validate_private_access()
                private_ok = True
            except Exception as exc:
                private_ok = False
                detail = f"private validation failed: {exc}"

        return SmokeResult(exchange, public_ok, private_ok, detail)

    async def run_many(
        self,
        exchanges: list[str] | None = None,
        *,
        private: bool = False,
    ) -> list[SmokeResult]:
        targets = exchanges or sorted(self.runtimes)
        return list(
            await asyncio.gather(
                *(self.run_exchange(exchange, private=private) for exchange in targets)
            )
        )

    def summarize(self, results: list[SmokeResult]) -> list[str]:
        lines = []
        for result in results:
            private_state = "n/a" if result.private_ok is None else ("ok" if result.private_ok else "failed")
            lines.append(
                f"{result.exchange}: public={'ok' if result.public_ok else 'failed'} "
                f"private={private_state} detail={result.detail}"
            )
        return lines
