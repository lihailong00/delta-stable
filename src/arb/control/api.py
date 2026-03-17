"""Control API with optional FastAPI integration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Callable

from pydantic import ConfigDict

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
from arb.schemas.base import ArbFrozenModel, SerializableValue

try:
    from fastapi import FastAPI  # type: ignore
except Exception:  # pragma: no cover
    FastAPI = None  # type: ignore


class LiteRoute(ArbFrozenModel):
    method: str
    path: str
    endpoint: object

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True, frozen=True)


class LiteApp:
    """Small stand-in app when FastAPI is unavailable."""

    def __init__(self) -> None:
        self.routes: list[LiteRoute] = []

    def get(self, path: str) -> Callable[[Callable[..., object]], Callable[..., object]]:
        def decorator(func: Callable[..., object]) -> Callable[..., object]:
            self.routes.append(LiteRoute(method="GET", path=path, endpoint=func))
            return func

        return decorator

    def post(self, path: str) -> Callable[[Callable[..., object]], Callable[..., object]]:
        def decorator(func: Callable[..., object]) -> Callable[..., object]:
            self.routes.append(LiteRoute(method="POST", path=path, endpoint=func))
            return func

        return decorator


class ControlAPI:
    """Imperative API service used by HTTP wrappers and tests."""

    def __init__(self, context: ApiContext) -> None:
        self.context = context

    @classmethod
    def from_service_bridge(
        cls,
        bridge: object,
        dispatcher: object,
        *,
        auth_token: str = "secret-token",
    ) -> "ControlAPI":
        return cls(bridge.build_api_context(dispatcher, auth_token=auth_token))  # type: ignore[attr-defined]

    def health(self) -> dict[str, SerializableValue]:
        return HealthResponse(status="ok").to_dict()

    def positions(self, token: str | None) -> list[dict[str, SerializableValue]]:
        self.context.require_token(token)
        return [self._coerce(PositionResponse, payload).to_dict() for payload in self.context.positions_provider()]

    def strategies(self, token: str | None) -> list[dict[str, SerializableValue]]:
        self.context.require_token(token)
        return [self._coerce(StrategyResponse, payload).to_dict() for payload in self.context.strategies_provider()]

    def orders(self, token: str | None) -> list[dict[str, SerializableValue]]:
        self.context.require_token(token)
        return [self._coerce(OrderResponse, payload).to_dict() for payload in self.context.orders_provider()]

    def workflows(self, token: str | None) -> list[dict[str, SerializableValue]]:
        self.context.require_token(token)
        return [self._coerce(WorkflowResponse, payload).to_dict() for payload in self.context.workflows_provider()]

    def funding_board(self, token: str | None) -> list[dict[str, SerializableValue]]:
        self.context.require_token(token)
        return [self._coerce(FundingBoardResponse, payload).to_dict() for payload in self.context.funding_board_provider()]

    def submit_command(self, token: str | None, request: CommandRequest) -> dict[str, SerializableValue]:
        self.context.require_token(token)
        response = self.context.command_handler(request)
        return self._coerce(CommandResponse, response).to_dict()

    def confirm_command(self, token: str | None, command_id: str, actor: str) -> dict[str, SerializableValue]:
        self.context.require_token(token)
        response = self.context.command_confirmer(command_id, actor)
        return self._coerce(CommandResponse, response).to_dict()

    def cancel_command(self, token: str | None, command_id: str, actor: str) -> dict[str, SerializableValue]:
        self.context.require_token(token)
        response = self.context.command_canceller(command_id, actor)
        return self._coerce(CommandResponse, response).to_dict()

    @staticmethod
    def _coerce[T: ArbFrozenModel](schema: type[T], payload: T | Mapping[str, SerializableValue]) -> T:
        if isinstance(payload, schema):
            return payload
        allowed = set(schema.model_fields)
        filtered = {key: value for key, value in payload.items() if key in allowed}
        return schema.model_validate(filtered)


def create_app(context: ApiContext) -> object:
    service = ControlAPI(context)
    app = FastAPI(title="arb-control") if FastAPI is not None else LiteApp()

    @app.get("/health")
    def health() -> dict[str, SerializableValue]:
        return service.health()

    @app.get("/positions")
    def positions(token: str | None = None) -> list[dict[str, SerializableValue]]:
        return service.positions(token)

    @app.get("/strategies")
    def strategies(token: str | None = None) -> list[dict[str, SerializableValue]]:
        return service.strategies(token)

    @app.get("/orders")
    def orders(token: str | None = None) -> list[dict[str, SerializableValue]]:
        return service.orders(token)

    @app.get("/workflows")
    def workflows(token: str | None = None) -> list[dict[str, SerializableValue]]:
        return service.workflows(token)

    @app.get("/funding-board")
    def funding_board(token: str | None = None) -> list[dict[str, SerializableValue]]:
        return service.funding_board(token)

    @app.post("/commands")
    def commands(request: Mapping[str, SerializableValue], token: str | None = None) -> dict[str, SerializableValue]:
        return service.submit_command(token, CommandRequest.model_validate(request))

    @app.post("/commands/{command_id}/confirm")
    def confirm(command_id: str, request: Mapping[str, SerializableValue], token: str | None = None) -> dict[str, SerializableValue]:
        return service.confirm_command(token, command_id, str(request["requested_by"]))

    @app.post("/commands/{command_id}/cancel")
    def cancel(command_id: str, request: Mapping[str, SerializableValue], token: str | None = None) -> dict[str, SerializableValue]:
        return service.cancel_command(token, command_id, str(request["requested_by"]))

    return app
