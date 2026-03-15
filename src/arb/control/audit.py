"""Audit log for manual control actions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


@dataclass(slots=True, frozen=True)
class AuditRecord:
    ts: datetime
    actor: str
    source: str
    action: str
    target: str
    outcome: str


class AuditLogger:
    """In-memory audit logger."""

    def __init__(self) -> None:
        self._records: list[AuditRecord] = []

    def record(self, *, actor: str, source: str, action: str, target: str, outcome: str) -> None:
        self._records.append(
            AuditRecord(
                ts=utc_now(),
                actor=actor,
                source=source,
                action=action,
                target=target,
                outcome=outcome,
            )
        )

    def records(self) -> list[AuditRecord]:
        return list(self._records)
