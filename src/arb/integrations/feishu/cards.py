"""Feishu card renderers."""

from __future__ import annotations

from collections.abc import Mapping

from arb.control.schemas import FundingBoardResponse, OrderResponse, PositionResponse, StrategyResponse, WorkflowResponse
from arb.integrations.feishu.schemas import FeishuCard
from arb.schemas.base import SerializableValue


def _coerce[T](schema: type[T], payload: T | Mapping[str, SerializableValue]) -> T:
    return payload if isinstance(payload, schema) else schema.model_validate(payload)  # type: ignore[attr-defined]


def build_positions_card(
    positions: list[PositionResponse | Mapping[str, SerializableValue]],
) -> FeishuCard:
    rows = [_coerce(PositionResponse, item) for item in positions]
    lines = [f"{item.exchange} {item.symbol} {item.direction} {item.quantity}" for item in rows] or ["No open positions"]
    return FeishuCard(
        config={"wide_screen_mode": True},
        header={"title": {"tag": "plain_text", "content": "Current Positions"}},
        elements=[{"tag": "markdown", "content": "\n".join(lines)}],
    )


def build_strategies_card(
    strategies: list[StrategyResponse | Mapping[str, SerializableValue]],
) -> FeishuCard:
    rows = [_coerce(StrategyResponse, item) for item in strategies]
    lines = [f"{item.name}: {item.status}" for item in rows] or ["No strategies"]
    return FeishuCard(
        config={"wide_screen_mode": True},
        header={"title": {"tag": "plain_text", "content": "Strategy Status"}},
        elements=[{"tag": "markdown", "content": "\n".join(lines)}],
    )


def build_orders_card(
    orders: list[OrderResponse | Mapping[str, SerializableValue]],
) -> FeishuCard:
    rows = [_coerce(OrderResponse, item) for item in orders]
    lines = [
        f"{item.exchange} {item.symbol} {item.order_id} {item.status} filled={item.filled_quantity}"
        for item in rows
    ] or ["No orders"]
    return FeishuCard(
        config={"wide_screen_mode": True},
        header={"title": {"tag": "plain_text", "content": "Order Status"}},
        elements=[{"tag": "markdown", "content": "\n".join(lines)}],
    )


def build_workflows_card(
    workflows: list[WorkflowResponse | Mapping[str, SerializableValue]],
) -> FeishuCard:
    rows = [_coerce(WorkflowResponse, item) for item in workflows]
    lines = [f"{item.workflow_id} {item.exchange} {item.symbol} {item.status}" for item in rows] or ["No workflows"]
    return FeishuCard(
        config={"wide_screen_mode": True},
        header={"title": {"tag": "plain_text", "content": "Funding Arb Workflows"}},
        elements=[{"tag": "markdown", "content": "\n".join(lines)}],
    )


def build_funding_board_card(
    rows: list[FundingBoardResponse | Mapping[str, SerializableValue]],
) -> FeishuCard:
    items = [_coerce(FundingBoardResponse, item) for item in rows]
    lines = [
        (
            f"{item.exchange} {item.symbol} "
            f"net={item.net_rate} interval={item.funding_interval_hours}h annualized={item.annualized_net_rate} "
            f"spread_bps={item.spread_bps} liquidity={item.liquidity_usd}"
        )
        for item in items
    ] or ["No funding opportunities"]
    return FeishuCard(
        config={"wide_screen_mode": True},
        header={"title": {"tag": "plain_text", "content": "Funding Board"}},
        elements=[{"tag": "markdown", "content": "\n".join(lines)}],
    )


def build_action_card(
    strategy_id: str,
    action: str,
    *,
    command_id: str | None = None,
    confirm_text: str | None = None,
    require_confirmation: bool = True,
) -> FeishuCard:
    actions: list[dict[str, SerializableValue]] = [
        {
            "tag": "button",
            "text": {"tag": "plain_text", "content": action.title()},
            "type": "primary",
            "value": {
                "action": action,
                "target": strategy_id,
                "command_id": command_id,
                "require_confirmation": require_confirmation,
            },
        }
    ]
    if command_id is not None:
        actions.extend(
            [
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "Confirm"},
                    "type": "primary",
                    "value": {"action": "confirm", "command_id": command_id},
                },
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "Cancel"},
                    "type": "default",
                    "value": {"action": "cancel", "command_id": command_id},
                },
            ]
        )
    return FeishuCard(
        config={"wide_screen_mode": True},
        header={"title": {"tag": "plain_text", "content": f"{action.title()} Strategy"}},
        elements=[
            {"tag": "markdown", "content": confirm_text or f"Execute `{action}` on `{strategy_id}`"},
            {"tag": "action", "actions": actions},
        ],
    )
