"""Command submission and dispatch."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from arb.control.audit import AuditLogger
from arb.control.commands import ControlCommand


class CommandDispatcher:
    """Queue, confirm and dispatch manual control commands."""

    def __init__(
        self,
        handler: Callable[[ControlCommand], dict[str, Any]],
        *,
        audit: AuditLogger | None = None,
        allowed_users: set[str] | None = None,
        confirmation_actions: set[str] | None = None,
    ) -> None:
        self.handler = handler
        self.audit = audit or AuditLogger()
        self.allowed_users = allowed_users or set()
        self.confirmation_actions = confirmation_actions or {"close_all"}
        self._seen_ids: set[str] = set()
        self._pending_confirmations: dict[str, ControlCommand] = {}
        self._queue: list[ControlCommand] = []

    def submit(self, command: ControlCommand) -> dict[str, Any]:
        self._authorize(command.requested_by)
        if command.command_id in self._seen_ids:
            self.audit.record(
                actor=command.requested_by,
                source=command.source,
                action=command.action,
                target=command.target,
                outcome="duplicate",
            )
            return {"accepted": False, "status": "duplicate", "command_id": command.command_id}

        self._seen_ids.add(command.command_id)
        if command.require_confirmation or command.action in self.confirmation_actions:
            self._pending_confirmations[command.command_id] = command
            self.audit.record(
                actor=command.requested_by,
                source=command.source,
                action=command.action,
                target=command.target,
                outcome="pending_confirmation",
            )
            return {"accepted": True, "status": "pending_confirmation", "command_id": command.command_id}

        self._queue.append(command)
        self.audit.record(
            actor=command.requested_by,
            source=command.source,
            action=command.action,
            target=command.target,
            outcome="queued",
        )
        return {"accepted": True, "status": "queued", "command_id": command.command_id}

    def confirm(self, command_id: str, actor: str) -> dict[str, Any]:
        self._authorize(actor)
        command = self._pending_confirmations.pop(command_id)
        self._queue.append(command)
        self.audit.record(
            actor=actor,
            source=command.source,
            action=command.action,
            target=command.target,
            outcome="confirmed",
        )
        return {"accepted": True, "status": "queued", "command_id": command_id}

    def cancel(self, command_id: str, actor: str) -> dict[str, Any]:
        self._authorize(actor)
        command = self._pending_confirmations.pop(command_id, None)
        if command is None:
            queue_index = next(
                (index for index, queued in enumerate(self._queue) if queued.command_id == command_id),
                None,
            )
            if queue_index is None:
                raise KeyError(command_id)
            command = self._queue.pop(queue_index)
        self.audit.record(
            actor=actor,
            source=command.source,
            action=command.action,
            target=command.target,
            outcome="canceled",
        )
        return {"accepted": True, "status": "canceled", "command_id": command_id}

    def dispatch_next(self) -> dict[str, Any] | None:
        if not self._queue:
            return None
        command = self._queue.pop(0)
        result = self.handler(command)
        self.audit.record(
            actor=command.requested_by,
            source=command.source,
            action=command.action,
            target=command.target,
            outcome=str(result.get("status", "dispatched")),
        )
        return result

    def queue_snapshot(self) -> dict[str, list[str]]:
        return {
            "queued": [command.command_id for command in self._queue],
            "pending_confirmation": list(self._pending_confirmations),
        }

    def _authorize(self, actor: str) -> None:
        if self.allowed_users and actor not in self.allowed_users:
            raise PermissionError("user is not allowed to submit control commands")
