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


def build_action_card(strategy_id: str, action: str, *, confirm_text: str | None = None) -> dict[str, Any]:
    return {
        "config": {"wide_screen_mode": True},
        "header": {"title": {"tag": "plain_text", "content": f"{action.title()} Strategy"}},
        "elements": [
            {"tag": "markdown", "content": confirm_text or f"Execute `{action}` on `{strategy_id}`"},
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": action.title()},
                        "type": "primary",
                        "value": {"action": action, "target": strategy_id},
                    }
                ],
            },
        ],
    }
