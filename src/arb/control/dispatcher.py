"""Command submission and dispatch."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from arb.control.audit import AuditLogger
from arb.control.commands import ControlCommand
from arb.control.schemas import CommandQueueSnapshot, CommandResponse
from arb.schemas.base import SerializableValue


class CommandDispatcher:
    """Queue, confirm and dispatch manual control commands."""

    def __init__(
        self,
        handler: Callable[[ControlCommand], CommandResponse | Mapping[str, SerializableValue]],
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

    def submit(self, command: ControlCommand) -> CommandResponse:
        self._authorize(command.requested_by)
        if command.command_id in self._seen_ids:
            self.audit.record(
                actor=command.requested_by,
                source=command.source,
                action=command.action,
                target=command.target,
                outcome="duplicate",
            )
            return CommandResponse(accepted=False, status="duplicate", command_id=command.command_id)

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
            return CommandResponse(accepted=True, status="pending_confirmation", command_id=command.command_id)

        self._queue.append(command)
        self.audit.record(
            actor=command.requested_by,
            source=command.source,
            action=command.action,
            target=command.target,
            outcome="queued",
        )
        return CommandResponse(accepted=True, status="queued", command_id=command.command_id)

    def confirm(self, command_id: str, actor: str) -> CommandResponse:
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
        return CommandResponse(accepted=True, status="queued", command_id=command_id)

    def cancel(self, command_id: str, actor: str) -> CommandResponse:
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
        return CommandResponse(accepted=True, status="canceled", command_id=command_id)

    def dispatch_next(self) -> CommandResponse | None:
        if not self._queue:
            return None
        command = self._queue.pop(0)
        return self.dispatch(command)

    def dispatch(self, command: ControlCommand) -> CommandResponse:
        raw_result = self.handler(command)
        result = (
            raw_result
            if isinstance(raw_result, CommandResponse)
            else CommandResponse.model_validate(
                {
                    "accepted": True,
                    **raw_result,
                }
            )
        )
        self.audit.record(
            actor=command.requested_by,
            source=command.source,
            action=command.action,
            target=command.target,
            outcome=result.status,
        )
        return result

    def dispatch_all(self) -> list[CommandResponse]:
        results: list[CommandResponse] = []
        while self._queue:
            dispatched = self.dispatch_next()
            if dispatched is not None:
                results.append(dispatched)
        return results

    def queue_snapshot(self) -> CommandQueueSnapshot:
        return CommandQueueSnapshot(
            queued=[command.command_id for command in self._queue],
            pending_confirmation=list(self._pending_confirmations),
        )

    def _authorize(self, actor: str) -> None:
        if self.allowed_users and actor not in self.allowed_users:
            raise PermissionError("user is not allowed to submit control commands")
