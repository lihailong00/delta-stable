"""Workflow result enums."""

from __future__ import annotations

from enum import StrEnum


class OpenPositionStatus(StrEnum):
    REJECTED = "rejected"
    OPENED = "opened"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


class ClosePositionStatus(StrEnum):
    CLOSED = "closed"
    REDUCED = "reduced"
    FAILED = "failed"
