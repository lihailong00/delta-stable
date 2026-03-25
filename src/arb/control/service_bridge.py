"""Bind the control plane to a running funding arbitrage service."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Protocol

from pydantic import ConfigDict

from arb.control.commands import ControlCommand
from arb.control.deps import ApiContext
from arb.control.dispatcher import CommandDispatcher
from arb.control.schemas import (
    CommandRequest,
    CommandResponse,
    OrderResponse,
    PositionResponse,
    StrategyResponse,
    WorkflowResponse,
)
from arb.models import MarketType
from arb.runtime.schemas import ActiveFundingArb, RecoveryPlan, WorkflowStateRecord
from arb.schemas.base import ArbModel, SerializableValue
from arb.storage.schemas import StoredOrderRow, StoredWorkflowStateRow


def _hedged_quantity(position: ActiveFundingArb) -> Decimal:
    """返回对冲仓位当前两条腿中的较大数量，用于控制面展示。"""

    return max(position.spot_quantity, position.perp_quantity)


class ServiceLike(Protocol):
    manager: object
    strategy_name: str
    position_quantity: Decimal
    active_positions: dict[str, ActiveFundingArb]


class RepositoryLike(Protocol):
    def save_workflow_state(self, **payload: object) -> None: ...

    def list_workflow_states(self) -> list[StoredWorkflowStateRow | Mapping[str, SerializableValue]]: ...

    def list_orders(self) -> list[StoredOrderRow | Mapping[str, SerializableValue]]: ...


class RecoveryLike(Protocol):
    async def recover(
        self,
        client: object,
        *,
        exchange: str,
        market_type: MarketType = MarketType.PERPETUAL,
        symbol: str | None = None,
    ) -> RecoveryPlan: ...


class PendingManualOpen(ArbModel):
    workflow_id: str
    exchange: str
    symbol: str
    quantity: Decimal
    requested_by: str

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class ServiceBridge:
    """Expose a live service instance to API providers and manual commands."""

    def __init__(
        self,
        *,
        service: ServiceLike,
        repository: RepositoryLike | None = None,
        recovery: RecoveryLike | None = None,
    ) -> None:
        self.service = service
        self.repository = repository
        self.recovery = recovery
        self.pending_manual_opens: dict[str, PendingManualOpen] = {}

    def build_api_context(
        self,
        dispatcher: CommandDispatcher,
        *,
        auth_token: str = "secret-token",
    ) -> ApiContext:
        return ApiContext(
            positions_provider=self.positions,
            strategies_provider=self.strategies,
            orders_provider=self.orders,
            workflows_provider=self.workflows,
            command_handler=lambda request: dispatcher.submit(self.command_from_payload(request)),
            command_confirmer=dispatcher.confirm,
            command_canceller=dispatcher.cancel,
            auth_token=auth_token,
        )

    def positions(self) -> list[PositionResponse]:
        return [
            PositionResponse(
                exchange=position.exchange,
                symbol=position.symbol,
                market_type=MarketType.PERPETUAL.value,
                quantity=str(_hedged_quantity(position)),
                direction="hedged",
            )
            for position in self.service.active_positions.values()
        ]

    def strategies(self) -> list[StrategyResponse]:
        status = "running" if self.service.active_positions else "idle"
        return [StrategyResponse(name=self.service.strategy_name, status=status)]

    def orders(self) -> list[OrderResponse]:
        if self.repository is None:
            return []
        return [OrderResponse.model_validate(payload) for payload in self.repository.list_orders()]

    def workflows(self) -> list[WorkflowResponse]:
        workflows = (
            []
            if self.repository is None
            else [WorkflowResponse.model_validate(payload) for payload in self.repository.list_workflow_states()]
        )
        workflows.extend(
            WorkflowResponse(
                workflow_id=item.workflow_id,
                workflow_type=self.service.strategy_name,
                exchange=item.exchange,
                symbol=item.symbol,
                status="manual_open_pending",
                payload={"quantity": str(item.quantity), "requested_by": item.requested_by},
            )
            for item in self.pending_manual_opens.values()
        )
        return workflows

    async def recovery_plan(
        self,
        client: object,
        *,
        exchange: str,
        market_type: MarketType = MarketType.PERPETUAL,
        symbol: str | None = None,
    ) -> RecoveryPlan:
        if self.recovery is None:
            raise RuntimeError("recovery is not configured")
        return await self.recovery.recover(
            client,
            exchange=exchange,
            market_type=market_type,
            symbol=symbol,
        )

    def command_from_payload(self, payload: CommandRequest | Mapping[str, SerializableValue]) -> ControlCommand:
        request = payload if isinstance(payload, CommandRequest) else CommandRequest.model_validate(payload)
        return ControlCommand(
            command_id=f"cmd-{len(self.pending_manual_opens) + 1}",
            action=request.action,
            target=request.target,
            requested_by=request.requested_by,
            require_confirmation=request.require_confirmation,
            payload=request.payload,
        )

    def handle_command(self, command: ControlCommand) -> CommandResponse:
        if command.action == "manual_open":
            return self.manual_open(command)
        if command.action == "manual_close":
            return self.manual_close(command)
        if command.action == "cancel_workflow":
            return self.cancel_workflow(command)
        if command.action == "close_all":
            return self.close_all(command)
        return CommandResponse(accepted=False, status="unsupported", command_id=command.command_id)

    def manual_open(self, command: ControlCommand) -> CommandResponse:
        exchange, symbol = self._split_exchange_symbol(command.target)
        workflow_id = self._workflow_id(exchange, symbol)
        quantity = Decimal(str(command.payload.get("quantity", self.service.position_quantity)))
        if not self.service.manager.acquire_slot(f"{exchange}:{symbol}"):  # type: ignore[attr-defined]
            return CommandResponse(accepted=False, status="slot_busy", command_id=command.command_id)
        self.pending_manual_opens[workflow_id] = PendingManualOpen(
            workflow_id=workflow_id,
            exchange=exchange,
            symbol=symbol,
            quantity=quantity,
            requested_by=command.requested_by,
        )
        self._save_workflow_state(
            workflow_id=workflow_id,
            exchange=exchange,
            symbol=symbol,
            status="manual_open_pending",
            payload={"quantity": str(quantity), "requested_by": command.requested_by},
        )
        return CommandResponse(accepted=True, status="queued", command_id=command.command_id)

    def manual_close(self, command: ControlCommand) -> CommandResponse:
        workflow_id = self._normalize_workflow_id(command.target)
        position = self.service.active_positions.pop(workflow_id, None)
        if position is None:
            raise KeyError(workflow_id)
        self.service.manager.release_slot(f"{position.exchange}:{position.symbol}")  # type: ignore[attr-defined]
        self._save_workflow_state(
            workflow_id=workflow_id,
            exchange=position.exchange,
            symbol=position.symbol,
            status="manual_close_requested",
            payload={"requested_by": command.requested_by},
        )
        return CommandResponse(accepted=True, status="queued", command_id=command.command_id)

    def cancel_workflow(self, command: ControlCommand) -> CommandResponse:
        workflow_id = self._normalize_workflow_id(command.target)
        pending = self.pending_manual_opens.pop(workflow_id, None)
        if pending is None:
            raise KeyError(workflow_id)
        self.service.manager.release_slot(f"{pending.exchange}:{pending.symbol}")  # type: ignore[attr-defined]
        self._save_workflow_state(
            workflow_id=workflow_id,
            exchange=pending.exchange,
            symbol=pending.symbol,
            status="canceled",
            payload={"requested_by": command.requested_by},
        )
        return CommandResponse(accepted=True, status="canceled", command_id=command.command_id)

    def close_all(self, command: ControlCommand) -> CommandResponse:
        for workflow_id, position in list(self.service.active_positions.items()):
            self.service.manager.release_slot(f"{position.exchange}:{position.symbol}")  # type: ignore[attr-defined]
            self.service.active_positions.pop(workflow_id, None)
            self._save_workflow_state(
                workflow_id=workflow_id,
                exchange=position.exchange,
                symbol=position.symbol,
                status="manual_close_requested",
                payload={"requested_by": command.requested_by, "scope": "all"},
            )
        return CommandResponse(accepted=True, status="queued", command_id=command.command_id)

    def _save_workflow_state(
        self,
        *,
        workflow_id: str,
        exchange: str,
        symbol: str,
        status: str,
        payload: dict[str, SerializableValue],
    ) -> None:
        if self.repository is None:
            return
        self.repository.save_workflow_state(
            workflow_id=workflow_id,
            workflow_type=self.service.strategy_name,
            exchange=exchange,
            symbol=symbol,
            status=status,
            payload=payload,
        )

    def _workflow_id(self, exchange: str, symbol: str) -> str:
        return f"{self.service.strategy_name}:{exchange}:{symbol}"

    def _normalize_workflow_id(self, target: str) -> str:
        if target.startswith(f"{self.service.strategy_name}:"):
            return target
        exchange, symbol = self._split_exchange_symbol(target)
        return self._workflow_id(exchange, symbol)

    @staticmethod
    def _split_exchange_symbol(target: str) -> tuple[str, str]:
        exchange, symbol = target.split(":", 1)
        return exchange, symbol
