"""Supervisor for long-running funding arbitrage loops."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from typing import Any

Runner = Callable[[], Awaitable[Any]]
HealthCheck = Callable[[], bool | Awaitable[bool]]
SleepFn = Callable[[float], Awaitable[None]]


@dataclass(slots=True)
class SupervisorState:
    completed_iterations: int = 0
    restart_count: int = 0
    last_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["healthy"] = self.last_error is None
        return payload


class RuntimeSupervisor:
    """Restart a failing async loop with bounded retries and health checks."""

    def __init__(
        self,
        runner: Runner,
        *,
        healthcheck: HealthCheck | None = None,
        max_restarts: int = 3,
        restart_delay: float = 0.1,
        sleep: SleepFn | None = None,
    ) -> None:
        self.runner = runner
        self.healthcheck = healthcheck
        self.max_restarts = max_restarts
        self.restart_delay = restart_delay
        self.sleep = sleep or asyncio.sleep
        self.state = SupervisorState()

    async def run_forever(self, *, iterations: int | None = None) -> list[Any]:
        results: list[Any] = []
        while iterations is None or self.state.completed_iterations < iterations:
            try:
                await self._ensure_healthy()
                results.append(await self.runner())
                self.state.completed_iterations += 1
                self.state.last_error = None
            except Exception as exc:
                self.state.restart_count += 1
                self.state.last_error = str(exc)
                if self.state.restart_count > self.max_restarts:
                    raise
                await self.sleep(self.restart_delay)
        return results

    def snapshot(self) -> dict[str, Any]:
        return self.state.to_dict()

    async def _ensure_healthy(self) -> None:
        if self.healthcheck is None:
            return
        result = self.healthcheck()
        healthy = await result if asyncio.iscoroutine(result) else result
        if not healthy:
            raise RuntimeError("healthcheck_failed")
