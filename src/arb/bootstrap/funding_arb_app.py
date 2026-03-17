"""Funding arbitrage application bootstrap helpers."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from arb.bootstrap.schemas import CommandHandlerMap, FundingArbCliArgs, FundingArbRunReport, to_serializable
from arb.control import ApiContext, CommandDispatcher, ControlAPI, ControlCommand
from arb.control.schemas import CommandRequest, CommandResponse, PositionResponse, StrategyResponse, WorkflowResponse
from arb.execution import OrderTracker, PairExecutor
from arb.models import MarketType
from arb.runtime import FundingArbService, LiveExchangeManager, OpportunityPipeline, RealtimeScanner, ScanTarget
from arb.runtime.protocols import LiveRuntimeProtocol
from arb.scanner.funding_scanner import FundingScanner
from arb.schemas.base import SerializableValue
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

    async def run_funding_arb(
        self,
        args: FundingArbCliArgs | object,
        *,
        dry_run: bool,
    ) -> FundingArbRunReport:
        cli_args = args if isinstance(args, FundingArbCliArgs) else FundingArbCliArgs.from_namespace(args)
        market_type = MarketType(cli_args.market_type)
        targets = [
            ScanTarget(exchange, symbol, market_type)
            for exchange in cli_args.exchange
            for symbol in cli_args.symbol
        ]
        iterations = cli_args.iterations
        results: list[dict[str, SerializableValue]] = []
        for _ in range(iterations):
            serialized = to_serializable(await self.service.run_once(targets, dry_run=dry_run))
            if not isinstance(serialized, dict):
                raise TypeError("funding arb service results must serialize to a mapping")
            results.append(serialized)
        return FundingArbRunReport(iterations=iterations, results=results)

    def cli_handlers(self) -> CommandHandlerMap:
        return {
            "funding-arb": lambda args: self.run_funding_arb(args, dry_run=False),
            "funding-arb-dry-run": lambda args: self.run_funding_arb(args, dry_run=True),
        }


def build_funding_arb_app(
    *,
    runtimes: Mapping[str, LiveRuntimeProtocol],
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
        strategies_provider=lambda: [StrategyResponse(name=service.strategy_name, status=_status_name(service))],
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


def _positions_payload(service: FundingArbService) -> list[PositionResponse]:
    return [
        PositionResponse(
            exchange=position.exchange,
            symbol=position.symbol,
            market_type=MarketType.PERPETUAL.value,
            quantity=str(position.quantity),
            direction="hedged",
        )
        for position in service.active_positions.values()
    ]


def _workflows_payload(service: FundingArbService) -> list[WorkflowResponse]:
    return [
        WorkflowResponse(
            workflow_id=position.workflow_id,
            workflow_type=service.strategy_name,
            exchange=position.exchange,
            symbol=position.symbol,
            status="open",
            payload={"opened_at": position.opened_at.isoformat()},
        )
        for position in service.active_positions.values()
    ]


def _command_from_payload(payload: CommandRequest | Mapping[str, SerializableValue]) -> ControlCommand:
    request = payload if isinstance(payload, CommandRequest) else CommandRequest.model_validate(payload)
    return ControlCommand(
        command_id=str(uuid4()),
        action=request.action,
        target=request.target,
        requested_by=request.requested_by,
        require_confirmation=request.require_confirmation,
        payload=request.payload,
    )


def _default_command_handler(command: ControlCommand) -> CommandResponse:
    return CommandResponse(accepted=True, status="queued", command_id=command.command_id)
