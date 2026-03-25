"""Control-plane enums."""

from __future__ import annotations

from enum import StrEnum


class HealthStatus(StrEnum):
    OK = "ok"


class ControlSource(StrEnum):
    API = "api"


class ControlAction(StrEnum):
    MANUAL_OPEN = "manual_open"
    MANUAL_CLOSE = "manual_close"
    CLOSE_ALL = "close_all"
    CANCEL_WORKFLOW = "cancel_workflow"


class CommandStatus(StrEnum):
    QUEUED = "queued"
    CANCELED = "canceled"
    DUPLICATE = "duplicate"
    PENDING_CONFIRMATION = "pending_confirmation"
    UNSUPPORTED = "unsupported"
    SLOT_BUSY = "slot_busy"
    DONE = "done"
