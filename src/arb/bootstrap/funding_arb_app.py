"""Funding arbitrage application bootstrap helpers."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

from arb.control import ApiContext, CommandDispatcher, ControlAPI, ControlCommand
from arb.execution import OrderTracker, PairExecutor
from arb.models import MarketType
from arb.runtime import FundingArbService, LiveExchangeManager, OpportunityPipeline, RealtimeScanner, ScanTarget
from arb.scanner.funding_scanner import FundingScanner
from arb.storage import Database, Repository
from arb.workflows import ClosePositionWorkflow, OpenPositionWorkflow, VenueClients


def _status_name(service: FundingArbService) -> str:
    return "running" if service.active_positions else "idle"


@dataclass(slots=True)
class FundingArbApp:
    manager: LiveExchangeManager
    funding_scanner: FundingScanner
    realtime_scanner: RealtimeScanner
    pipeline: OpportunityPipeline
    repository: Repository | None
    service: FundingArbService
    dispatcher: CommandDispatcher
    control_api: ControlAPI

    async def run_funding_arb(self, args: Any, *, dry_run: bool) -> dict[str, Any]:
        market_type = MarketType(str(getattr(args, "market_type", "perpetual")))
        targets = [
            ScanTarget(exchange, symbol, market_type)
            for exchange in getattr(args, "exchange")
            for symbol in getattr(args, "symbol")
        ]
        iterations = int(getattr(args, "iterations", 1))
        results: list[dict[str, Any]] = []
        for _ in range(iterations):
            results.append(await self.service.run_once(targets, dry_run=dry_run))
        return {"iterations": iterations, "results": results}

    def cli_handlers(self) -> dict[str, Any]:
        return {
            "funding-arb": lambda args: self.run_funding_arb(args, dry_run=False),
            "funding-arb-dry-run": lambda args: self.run_funding_arb(args, dry_run=True),
        }


def build_funding_arb_app(
    *,
    runtimes: Mapping[str, Any],
    venues: Mapping[str, VenueClients],
    repository: Repository | None = None,
    database_path: str | Path | None = None,
    min_net_rate: Decimal = Decimal("0.0001"),
    position_quantity: Decimal = Decimal("1"),
) -> FundingArbApp:
    if repository is None and database_path is not None:
        database = Database(database_path)
        database.initialize()
        repository = Repository(database)

    manager = LiveExchangeManager(runtimes)
    funding_scanner = FundingScanner(min_net_rate=min_net_rate)
    pipeline = OpportunityPipeline(repository=repository)
    realtime_scanner = RealtimeScanner(manager, funding_scanner, pipeline, interval=0)
    executor = PairExecutor(tracker=OrderTracker(max_polls=1, poll_interval=0, sleep=_noop_sleep))
    service = FundingArbService(
        scanner=realtime_scanner,
        open_workflow=OpenPositionWorkflow(executor=executor),
        close_workflow=ClosePositionWorkflow(executor=executor),
        venues=dict(venues),
        manager=manager,
        pipeline=pipeline,
        position_quantity=position_quantity,
    )
    dispatcher = CommandDispatcher(
        _default_command_handler,
        confirmation_actions={"manual_open", "manual_close", "close_all", "cancel_workflow"},
    )
    context = ApiContext(
        positions_provider=lambda: _positions_payload(service),
        strategies_provider=lambda: [{"name": service.strategy_name, "status": _status_name(service)}],
        orders_provider=(repository.list_orders if repository is not None else (lambda: [])),
        workflows_provider=(
            repository.list_workflow_states
            if repository is not None
            else (lambda: _workflows_payload(service))
        ),
        command_handler=lambda payload: dispatcher.submit(_command_from_payload(payload)),
        command_confirmer=dispatcher.confirm,
        command_canceller=dispatcher.cancel,
    )
    return FundingArbApp(
        manager=manager,
        funding_scanner=funding_scanner,
        realtime_scanner=realtime_scanner,
        pipeline=pipeline,
        repository=repository,
        service=service,
        dispatcher=dispatcher,
        control_api=ControlAPI(context),
    )


async def _noop_sleep(_: float) -> None:
    return None


def _positions_payload(service: FundingArbService) -> list[dict[str, Any]]:
    return [
        {
            "exchange": position.exchange,
            "symbol": position.symbol,
            "market_type": MarketType.PERPETUAL.value,
            "quantity": str(position.quantity),
            "direction": "hedged",
        }
        for position in service.active_positions.values()
    ]


def _workflows_payload(service: FundingArbService) -> list[dict[str, Any]]:
    return [
        {
            "workflow_id": position.workflow_id,
            "workflow_type": service.strategy_name,
            "exchange": position.exchange,
            "symbol": position.symbol,
            "status": "open",
            "payload": {"opened_at": position.opened_at.isoformat()},
        }
        for position in service.active_positions.values()
    ]


def _command_from_payload(payload: Mapping[str, Any]) -> ControlCommand:
    return ControlCommand(
        command_id=str(payload.get("command_id", uuid4())),
        action=str(payload["action"]),
        target=str(payload["target"]),
        requested_by=str(payload["requested_by"]),
        require_confirmation=bool(payload.get("require_confirmation", False)),
        payload=dict(payload.get("payload", {})),
    )


def _default_command_handler(command: ControlCommand) -> dict[str, Any]:
    return {
        "accepted": True,
        "status": "queued",
        "command_id": command.command_id,
        "action": command.action,
        "target": command.target,
    }
