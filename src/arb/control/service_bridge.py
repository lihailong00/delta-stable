"""Bind the control plane to a running funding arbitrage service."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from arb.control.commands import ControlCommand
from arb.control.deps import ApiContext
from arb.control.dispatcher import CommandDispatcher
from arb.models import MarketType


@dataclass(slots=True)
class PendingManualOpen:
    workflow_id: str
    exchange: str
    symbol: str
    quantity: Decimal
    requested_by: str


class ServiceBridge:
    """Expose a live service instance to API providers and manual commands."""

    def __init__(
        self,
        *,
        service: Any,
        repository: Any | None = None,
        recovery: Any | None = None,
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
            command_handler=lambda payload: dispatcher.submit(self.command_from_payload(payload)),
            command_confirmer=dispatcher.confirm,
            command_canceller=dispatcher.cancel,
            auth_token=auth_token,
        )

    def positions(self) -> list[dict[str, Any]]:
        return [
            {
                "exchange": position.exchange,
                "symbol": position.symbol,
                "market_type": MarketType.PERPETUAL.value,
                "quantity": str(getattr(position, "quantity", Decimal("0"))),
                "direction": "hedged",
            }
            for position in self.service.active_positions.values()
        ]

    def strategies(self) -> list[dict[str, Any]]:
        status = "running" if self.service.active_positions else "idle"
        return [{"name": self.service.strategy_name, "status": status}]

    def orders(self) -> list[dict[str, Any]]:
        return [] if self.repository is None else self.repository.list_orders()

    def workflows(self) -> list[dict[str, Any]]:
        workflows = [] if self.repository is None else list(self.repository.list_workflow_states())
        workflows.extend(
            {
                "workflow_id": item.workflow_id,
                "workflow_type": self.service.strategy_name,
                "exchange": item.exchange,
                "symbol": item.symbol,
                "status": "manual_open_pending",
                "payload": {"quantity": str(item.quantity), "requested_by": item.requested_by},
            }
            for item in self.pending_manual_opens.values()
        )
        return workflows

    async def recovery_plan(
        self,
        client: Any,
        *,
        exchange: str,
        market_type: MarketType = MarketType.PERPETUAL,
        symbol: str | None = None,
    ) -> Any:
        if self.recovery is None:
            raise RuntimeError("recovery is not configured")
        return await self.recovery.recover(
            client,
            exchange=exchange,
            market_type=market_type,
            symbol=symbol,
        )

    def command_from_payload(self, payload: dict[str, Any]) -> ControlCommand:
        return ControlCommand(
            command_id=str(payload.get("command_id", "")) or f"cmd-{len(self.pending_manual_opens) + 1}",
            action=str(payload["action"]),
            target=str(payload["target"]),
            requested_by=str(payload["requested_by"]),
            source=str(payload.get("source", "api")),
            require_confirmation=bool(payload.get("require_confirmation", False)),
            payload=dict(payload.get("payload", {})),
        )

    def handle_command(self, command: ControlCommand) -> dict[str, Any]:
        if command.action == "manual_open":
            return self.manual_open(command)
        if command.action == "manual_close":
            return self.manual_close(command)
        if command.action == "cancel_workflow":
            return self.cancel_workflow(command)
        if command.action == "close_all":
            return self.close_all(command)
        return {
            "accepted": False,
            "status": "unsupported",
            "command_id": command.command_id,
            "action": command.action,
        }

    def manual_open(self, command: ControlCommand) -> dict[str, Any]:
        exchange, symbol = self._split_exchange_symbol(command.target)
        workflow_id = self._workflow_id(exchange, symbol)
        quantity = Decimal(str(command.payload.get("quantity", getattr(self.service, "position_quantity", "1"))))
        if not self.service.manager.acquire_slot(f"{exchange}:{symbol}"):
            return {"accepted": False, "status": "slot_busy", "command_id": command.command_id}
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
        return {"accepted": True, "status": "queued", "command_id": command.command_id}

    def manual_close(self, command: ControlCommand) -> dict[str, Any]:
        workflow_id = self._normalize_workflow_id(command.target)
        position = self.service.active_positions.pop(workflow_id, None)
        if position is None:
            raise KeyError(workflow_id)
        self.service.manager.release_slot(f"{position.exchange}:{position.symbol}")
        self._save_workflow_state(
            workflow_id=workflow_id,
            exchange=position.exchange,
            symbol=position.symbol,
            status="manual_close_requested",
            payload={"requested_by": command.requested_by},
        )
        return {"accepted": True, "status": "queued", "command_id": command.command_id}

    def cancel_workflow(self, command: ControlCommand) -> dict[str, Any]:
        workflow_id = self._normalize_workflow_id(command.target)
        pending = self.pending_manual_opens.pop(workflow_id, None)
        if pending is None:
            raise KeyError(workflow_id)
        self.service.manager.release_slot(f"{pending.exchange}:{pending.symbol}")
        self._save_workflow_state(
            workflow_id=workflow_id,
            exchange=pending.exchange,
            symbol=pending.symbol,
            status="canceled",
            payload={"requested_by": command.requested_by},
        )
        return {"accepted": True, "status": "canceled", "command_id": command.command_id}

    def close_all(self, command: ControlCommand) -> dict[str, Any]:
        for workflow_id, position in list(self.service.active_positions.items()):
            self.service.manager.release_slot(f"{position.exchange}:{position.symbol}")
            self.service.active_positions.pop(workflow_id, None)
            self._save_workflow_state(
                workflow_id=workflow_id,
                exchange=position.exchange,
                symbol=position.symbol,
                status="manual_close_requested",
                payload={"requested_by": command.requested_by, "scope": "all"},
            )
        return {"accepted": True, "status": "queued", "command_id": command.command_id}

    def _save_workflow_state(
        self,
        *,
        workflow_id: str,
        exchange: str,
        symbol: str,
        status: str,
        payload: dict[str, Any],
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
