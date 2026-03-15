"""Alert dispatching with dedupe."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


@dataclass(slots=True, frozen=True)
class Alert:
    key: str
    message: str
    severity: str


class AlertManager:
    """Dispatch alerts while suppressing duplicates within a window."""

    def __init__(
        self,
        sender: Callable[[Alert], None],
        *,
        dedupe_window: timedelta = timedelta(minutes=5),
    ) -> None:
        self.sender = sender
        self.dedupe_window = dedupe_window
        self._last_sent: dict[str, datetime] = {}

    def send(self, alert: Alert, *, now: datetime | None = None) -> bool:
        current = now or utc_now()
        last_sent = self._last_sent.get(alert.key)
        if last_sent and current - last_sent < self.dedupe_window:
            return False
        self.sender(alert)
        self._last_sent[alert.key] = current
        return True
