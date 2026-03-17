"""Control API with optional FastAPI integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from arb.control.deps import ApiContext
from arb.control.schemas import (
    CommandRequest,
    CommandResponse,
    FundingBoardResponse,
    HealthResponse,
    OrderResponse,
    PositionResponse,
    StrategyResponse,
    WorkflowResponse,
)

try:
    from fastapi import FastAPI  # type: ignore
except Exception:  # pragma: no cover
    FastAPI = None  # type: ignore


@dataclass(slots=True, frozen=True)
class LiteRoute:
    method: str
    path: str
    endpoint: Any


class LiteApp:
    """Small stand-in app when FastAPI is unavailable."""

    def __init__(self) -> None:
        self.routes: list[LiteRoute] = []

    def get(self, path: str):
        def decorator(func):
            self.routes.append(LiteRoute("GET", path, func))
            return func

        return decorator

    def post(self, path: str):
        def decorator(func):
            self.routes.append(LiteRoute("POST", path, func))
            return func

        return decorator


class ControlAPI:
    """Imperative API service used by HTTP wrappers and tests."""

    def __init__(self, context: ApiContext) -> None:
        self.context = context

    def health(self) -> dict[str, Any]:
        return HealthResponse(status="ok").to_dict()

    def positions(self, token: str | None) -> list[dict[str, Any]]:
        self.context.require_token(token)
        return [PositionResponse(**payload).to_dict() for payload in self.context.positions_provider()]

    def strategies(self, token: str | None) -> list[dict[str, Any]]:
        self.context.require_token(token)
        return [StrategyResponse(**payload).to_dict() for payload in self.context.strategies_provider()]

    def orders(self, token: str | None) -> list[dict[str, Any]]:
        self.context.require_token(token)
        return [OrderResponse(**payload).to_dict() for payload in self.context.orders_provider()]

    def workflows(self, token: str | None) -> list[dict[str, Any]]:
        self.context.require_token(token)
        return [WorkflowResponse(**payload).to_dict() for payload in self.context.workflows_provider()]

    def funding_board(self, token: str | None) -> list[dict[str, Any]]:
        self.context.require_token(token)
        return [FundingBoardResponse(**payload).to_dict() for payload in self.context.funding_board_provider()]

    def submit_command(self, token: str | None, request: CommandRequest) -> dict[str, Any]:
        self.context.require_token(token)
        response = self.context.command_handler(request.to_dict())
        return CommandResponse(
            accepted=bool(response["accepted"]),
            command_id=str(response["command_id"]),
            status=str(response.get("status", "queued")),
        ).to_dict()

    def confirm_command(self, token: str | None, command_id: str, actor: str) -> dict[str, Any]:
        self.context.require_token(token)
        response = self.context.command_confirmer(command_id, actor)
        return CommandResponse(
            accepted=bool(response["accepted"]),
            command_id=str(response["command_id"]),
            status=str(response.get("status", "queued")),
        ).to_dict()

    def cancel_command(self, token: str | None, command_id: str, actor: str) -> dict[str, Any]:
        self.context.require_token(token)
        response = self.context.command_canceller(command_id, actor)
        return CommandResponse(
            accepted=bool(response["accepted"]),
            command_id=str(response["command_id"]),
            status=str(response.get("status", "canceled")),
        ).to_dict()


def create_app(context: ApiContext) -> Any:
    service = ControlAPI(context)
    app = FastAPI(title="arb-control") if FastAPI is not None else LiteApp()

    @app.get("/health")
    def health() -> dict[str, Any]:
        return service.health()

    @app.get("/positions")
    def positions(token: str | None = None) -> list[dict[str, Any]]:
        return service.positions(token)

    @app.get("/strategies")
    def strategies(token: str | None = None) -> list[dict[str, Any]]:
        return service.strategies(token)

    @app.get("/orders")
    def orders(token: str | None = None) -> list[dict[str, Any]]:
        return service.orders(token)

    @app.get("/workflows")
    def workflows(token: str | None = None) -> list[dict[str, Any]]:
        return service.workflows(token)

    @app.get("/funding-board")
    def funding_board(token: str | None = None) -> list[dict[str, Any]]:
        return service.funding_board(token)

    @app.post("/commands")
    def commands(request: dict[str, Any], token: str | None = None) -> dict[str, Any]:
        return service.submit_command(token, CommandRequest(**request))

    @app.post("/commands/{command_id}/confirm")
    def confirm(command_id: str, request: dict[str, Any], token: str | None = None) -> dict[str, Any]:
        return service.confirm_command(token, command_id, str(request["requested_by"]))

    @app.post("/commands/{command_id}/cancel")
    def cancel(command_id: str, request: dict[str, Any], token: str | None = None) -> dict[str, Any]:
        return service.cancel_command(token, command_id, str(request["requested_by"]))

    return app
