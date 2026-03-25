from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arb.control.api import ControlAPI
from arb.control.commands import ControlCommand
from arb.control.dispatcher import CommandDispatcher
from arb.control.schemas import CommandRequest
from arb.control.service_bridge import ServiceBridge
from arb.runtime.exchange_manager import LiveExchangeManager
from arb.runtime.funding_arb_service import ActiveFundingArb


@dataclass
class _Service:
    manager: LiveExchangeManager
    strategy_name: str = "funding_spot_perp"
    position_quantity: Decimal = Decimal("1")

    def __post_init__(self) -> None:
        self.active_positions: dict[str, ActiveFundingArb] = {}


class _Repository:
    def __init__(self) -> None:
        self.workflows: list[dict[str, object]] = []

    def save_workflow_state(self, **payload) -> None:
        self.workflows.append(payload)

    def list_workflow_states(self) -> list[dict[str, object]]:
        return list(self.workflows)

    def list_orders(self) -> list[dict[str, object]]:
        return []


class TestServiceBridge:
    def setup_method(self) -> None:
        self.service = _Service(manager=LiveExchangeManager({}))
        self.repository = _Repository()
        self.bridge = ServiceBridge(service=self.service, repository=self.repository)
        self.dispatcher = CommandDispatcher(
            self.bridge.handle_command,
            confirmation_actions={"manual_open", "manual_close", "close_all", "cancel_workflow"},
        )

    def test_manual_open_and_cancel_workflow(self) -> None:
        api = ControlAPI.from_service_bridge(self.bridge, self.dispatcher, auth_token="abc")

        pending = api.submit_command(
            "abc",
            CommandRequest(
                action="manual_open",
                target="binance:BTC/USDT",
                requested_by="alice",
                require_confirmation=True,
            ),
        )
        assert pending["status"] == "pending_confirmation"

        api.confirm_command("abc", pending["command_id"], "alice")
        self.dispatcher.dispatch_all()

        assert self.service.manager.has_slot("binance:BTC/USDT")
        assert self.bridge.workflows()[-1]["status"] == "manual_open_pending"

        cancel = ControlCommand(
            command_id="cmd-cancel",
            action="cancel_workflow",
            target="funding_spot_perp:binance:BTC/USDT",
            requested_by="alice",
        )
        self.bridge.handle_command(cancel)
        assert not self.service.manager.has_slot("binance:BTC/USDT")
        assert self.repository.workflows[-1]["status"] == "canceled"

    def test_manual_close_removes_active_position(self) -> None:
        workflow_id = "funding_spot_perp:binance:BTC/USDT"
        self.service.active_positions[workflow_id] = ActiveFundingArb(
            workflow_id=workflow_id,
            exchange="binance",
            symbol="BTC/USDT",
            spot_quantity=Decimal("1"),
            perp_quantity=Decimal("1"),
            opened_at=datetime.now(tz=timezone.utc),
        )
        self.service.manager.acquire_slot("binance:BTC/USDT")

        result = self.bridge.handle_command(
            ControlCommand(
                command_id="cmd-close",
                action="manual_close",
                target=workflow_id,
                requested_by="alice",
            )
        )

        assert result["status"] == "queued"
        assert workflow_id not in self.service.active_positions
        assert not self.service.manager.has_slot("binance:BTC/USDT")
        assert self.repository.workflows[-1]["status"] == "manual_close_requested"

    def test_positions_use_larger_leg_quantity_for_display(self) -> None:
        workflow_id = "funding_spot_perp:binance:BTC/USDT"
        self.service.active_positions[workflow_id] = ActiveFundingArb(
            workflow_id=workflow_id,
            exchange="binance",
            symbol="BTC/USDT",
            spot_quantity=Decimal("0.8"),
            perp_quantity=Decimal("1"),
            opened_at=datetime.now(tz=timezone.utc),
        )

        positions = self.bridge.positions()

        assert positions[0]["quantity"] == "1"
