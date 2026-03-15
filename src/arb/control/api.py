"""Control API with optional FastAPI integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from arb.control.deps import ApiContext
from arb.control.schemas import CommandRequest, CommandResponse, HealthResponse, PositionResponse, StrategyResponse

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

    def submit_command(self, token: str | None, request: CommandRequest) -> dict[str, Any]:
        self.context.require_token(token)
        response = self.context.command_handler(request.to_dict())
        return CommandResponse(accepted=bool(response["accepted"]), command_id=str(response["command_id"])).to_dict()


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

    @app.post("/commands")
    def commands(request: dict[str, Any], token: str | None = None) -> dict[str, Any]:
        return service.submit_command(token, CommandRequest(**request))

    return app
