"""Feishu card renderers."""

from __future__ import annotations

from typing import Any


def build_positions_card(positions: list[dict[str, Any]]) -> dict[str, Any]:
    lines = [
        f"{item['exchange']} {item['symbol']} {item['direction']} {item['quantity']}"
        for item in positions
    ] or ["No open positions"]
    return {
        "config": {"wide_screen_mode": True},
        "header": {"title": {"tag": "plain_text", "content": "Current Positions"}},
        "elements": [{"tag": "markdown", "content": "\n".join(lines)}],
    }


def build_strategies_card(strategies: list[dict[str, Any]]) -> dict[str, Any]:
    lines = [f"{item['name']}: {item['status']}" for item in strategies] or ["No strategies"]
    return {
        "config": {"wide_screen_mode": True},
        "header": {"title": {"tag": "plain_text", "content": "Strategy Status"}},
        "elements": [{"tag": "markdown", "content": "\n".join(lines)}],
    }


def build_orders_card(orders: list[dict[str, Any]]) -> dict[str, Any]:
    lines = [
        f"{item['exchange']} {item['symbol']} {item['order_id']} {item['status']} filled={item['filled_quantity']}"
        for item in orders
    ] or ["No orders"]
    return {
        "config": {"wide_screen_mode": True},
        "header": {"title": {"tag": "plain_text", "content": "Order Status"}},
        "elements": [{"tag": "markdown", "content": "\n".join(lines)}],
    }


def build_workflows_card(workflows: list[dict[str, Any]]) -> dict[str, Any]:
    lines = [
        f"{item['workflow_id']} {item['exchange']} {item['symbol']} {item['status']}"
        for item in workflows
    ] or ["No workflows"]
    return {
        "config": {"wide_screen_mode": True},
        "header": {"title": {"tag": "plain_text", "content": "Funding Arb Workflows"}},
        "elements": [{"tag": "markdown", "content": "\n".join(lines)}],
    }


def build_action_card(
    strategy_id: str,
    action: str,
    *,
    command_id: str | None = None,
    confirm_text: str | None = None,
    require_confirmation: bool = True,
) -> dict[str, Any]:
    actions = [
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
    return {
        "config": {"wide_screen_mode": True},
        "header": {"title": {"tag": "plain_text", "content": f"{action.title()} Strategy"}},
        "elements": [
            {"tag": "markdown", "content": confirm_text or f"Execute `{action}` on `{strategy_id}`"},
            {"tag": "action", "actions": actions},
        ],
    }
