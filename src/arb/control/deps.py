"""Control API dependencies."""

from __future__ import annotations

from collections.abc import Callable

from pydantic import ConfigDict

from arb.control.enums import CommandStatus
from arb.control.schemas import (
    CommandRequest,
    CommandResponse,
    FundingBoardResponse,
    OrderResponse,
    PositionResponse,
    StrategyResponse,
    WorkflowResponse,
)
from arb.schemas.base import ArbModel

PositionsProvider = Callable[[], list[PositionResponse]]
StrategiesProvider = Callable[[], list[StrategyResponse]]
OrdersProvider = Callable[[], list[OrderResponse]]
WorkflowsProvider = Callable[[], list[WorkflowResponse]]
FundingBoardProvider = Callable[[], list[FundingBoardResponse]]
CommandHandler = Callable[[CommandRequest], CommandResponse]
CommandDecisionHandler = Callable[[str, str], CommandResponse]


class ApiContext(ArbModel):
    positions_provider: PositionsProvider = lambda: []
    strategies_provider: StrategiesProvider = lambda: []
    orders_provider: OrdersProvider = lambda: []
    workflows_provider: WorkflowsProvider = lambda: []
    funding_board_provider: FundingBoardProvider = lambda: []
    command_handler: CommandHandler = lambda command: CommandResponse(
        accepted=True,
        command_id="cmd-1",
        status=CommandStatus.QUEUED,
    )
    command_confirmer: CommandDecisionHandler = lambda command_id, actor: CommandResponse(
        accepted=True,
        command_id=command_id,
        status=CommandStatus.QUEUED,
    )
    command_canceller: CommandDecisionHandler = lambda command_id, actor: CommandResponse(
        accepted=True,
        command_id=command_id,
        status=CommandStatus.CANCELED,
    )
    auth_token: str = "secret-token"

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        arbitrary_types_allowed=True,
    )

    def require_token(self, token: str | None) -> None:
        if token != self.auth_token:
            raise PermissionError("invalid api token")
