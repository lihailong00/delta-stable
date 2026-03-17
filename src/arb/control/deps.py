"""Control API dependencies."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from pydantic import ConfigDict

from arb.control.schemas import (
    CommandRequest,
    CommandResponse,
    FundingBoardResponse,
    OrderResponse,
    PositionResponse,
    StrategyResponse,
    WorkflowResponse,
)
from arb.schemas.base import ArbModel, SerializableValue

PositionsProvider = Callable[[], list[PositionResponse | Mapping[str, SerializableValue]]]
StrategiesProvider = Callable[[], list[StrategyResponse | Mapping[str, SerializableValue]]]
OrdersProvider = Callable[[], list[OrderResponse | Mapping[str, SerializableValue]]]
WorkflowsProvider = Callable[[], list[WorkflowResponse | Mapping[str, SerializableValue]]]
FundingBoardProvider = Callable[[], list[FundingBoardResponse | Mapping[str, SerializableValue]]]
CommandHandler = Callable[[CommandRequest], CommandResponse | Mapping[str, SerializableValue]]
CommandDecisionHandler = Callable[[str, str], CommandResponse | Mapping[str, SerializableValue]]


class ApiContext(ArbModel):
    positions_provider: PositionsProvider = lambda: []
    strategies_provider: StrategiesProvider = lambda: []
    orders_provider: OrdersProvider = lambda: []
    workflows_provider: WorkflowsProvider = lambda: []
    funding_board_provider: FundingBoardProvider = lambda: []
    command_handler: CommandHandler = lambda command: CommandResponse(
        accepted=True,
        command_id="cmd-1",
        status="queued",
    )
    command_confirmer: CommandDecisionHandler = lambda command_id, actor: CommandResponse(
        accepted=True,
        command_id=command_id,
        status="queued",
    )
    command_canceller: CommandDecisionHandler = lambda command_id, actor: CommandResponse(
        accepted=True,
        command_id=command_id,
        status="canceled",
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
