from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arb.runtime.supervisor import RuntimeSupervisor


async def _sleep(_: float) -> None:
    return None


@pytest.mark.asyncio
async def test_supervisor_restarts_once_then_completes() -> None:
    state = {"count": 0}

    async def runner() -> str:
        state["count"] += 1
        if state["count"] == 1:
            raise RuntimeError("boom")
        return f"ok-{state['count']}"

    supervisor = RuntimeSupervisor(runner, max_restarts=1, sleep=_sleep)

    results = await supervisor.run_forever(iterations=1)

    assert results == ["ok-2"]
    assert supervisor.snapshot()["restart_count"] == 1


@pytest.mark.asyncio
async def test_supervisor_fails_after_healthcheck_budget_exhausted() -> None:
    async def runner() -> str:
        return "never"

    supervisor = RuntimeSupervisor(
        runner,
        healthcheck=lambda: False,
        max_restarts=1,
        sleep=_sleep,
    )

    with pytest.raises(RuntimeError, match="healthcheck_failed"):
        await supervisor.run_forever(iterations=1)
