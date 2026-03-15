"""Health checks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


@dataclass(slots=True)
class ComponentHealth:
    name: str
    last_seen_at: datetime


class HealthChecker:
    """Track component liveness."""

    def __init__(self, *, max_staleness: timedelta = timedelta(seconds=60)) -> None:
        self.max_staleness = max_staleness
        self._components: dict[str, ComponentHealth] = {}

    def heartbeat(self, component: str, *, at: datetime | None = None) -> None:
        self._components[component] = ComponentHealth(component, at or utc_now())

    def unhealthy_components(self, *, now: datetime | None = None) -> list[str]:
        current = now or utc_now()
        return [
            component.name
            for component in self._components.values()
            if current - component.last_seen_at > self.max_staleness
        ]

    def is_healthy(self, *, now: datetime | None = None) -> bool:
        return not self.unhealthy_components(now=now)
