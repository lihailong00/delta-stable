"""离线示例：Control API、命令分发和审计。

运行：
PYTHONPATH=src uv run python examples/control_api.py
"""

from __future__ import annotations

import json

from arb.control.api import ControlAPI, create_app
from arb.control.commands import ControlCommand
from arb.control.deps import ApiContext
from arb.control.dispatcher import CommandDispatcher
from arb.control.schemas import CommandRequest


def main() -> None:
    dispatcher = CommandDispatcher(
        handler=lambda command: {
            "accepted": True,
            "status": "executed",
            "command_id": command.command_id,
            "target": command.target,
        },
        allowed_users={"alice"},
    )
    context = ApiContext(
        positions_provider=lambda: [
            {
                "exchange": "binance",
                "symbol": "BTC/USDT",
                "market_type": "spot",
                "quantity": "1",
                "direction": "long",
            }
        ],
        strategies_provider=lambda: [{"name": "spot_perp", "status": "running"}],
        command_handler=lambda payload: dispatcher.submit(
            ControlCommand(
                command_id="cmd-100",
                action=payload["action"],
                target=payload["target"],
                requested_by=payload["requested_by"],
            )
        ),
        auth_token="secret-token",
    )
    service = ControlAPI(context)

    print("health", service.health())
    print("positions", json.dumps(service.positions("secret-token"), indent=2))
    print("strategies", json.dumps(service.strategies("secret-token"), indent=2))
    accepted = service.submit_command(
        "secret-token",
        CommandRequest(action="close", target="spot_perp:BTC/USDT", requested_by="alice"),
    )
    print("command accepted", accepted)
    print("dispatch result", dispatcher.dispatch_next())
    print("audit trail", dispatcher.audit.records())

    app = create_app(context)
    print("routes", [route.path for route in app.routes])


if __name__ == "__main__":
    main()
