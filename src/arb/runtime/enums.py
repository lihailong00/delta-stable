"""Runtime and workflow lifecycle enums."""

from __future__ import annotations

from enum import StrEnum


class WorkflowStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    OPENING = "opening"
    OPEN = "open"
    WARNING = "warning"
    CLOSING = "closing"
    CLOSED = "closed"
    REDUCED = "reduced"
    FAILED = "failed"
    REJECTED = "rejected"
    MANUAL_OPEN_PENDING = "manual_open_pending"
    MANUAL_CLOSE_REQUESTED = "manual_close_requested"
    CANCELED = "canceled"


class ServiceStatus(StrEnum):
    RUNNING = "running"
    IDLE = "idle"
