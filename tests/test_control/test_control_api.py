from __future__ import annotations

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arb.control.api import ControlAPI, create_app
from arb.control.deps import ApiContext
from arb.control.schemas import CommandRequest


class ControlApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = ApiContext(
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
            command_handler=lambda command: {"accepted": True, "command_id": "cmd-42", **command},
            auth_token="abc",
        )
        self.api = ControlAPI(self.context)

    def test_health_check(self) -> None:
        self.assertEqual(self.api.health()["status"], "ok")

    def test_positions_and_strategies_require_auth(self) -> None:
        with self.assertRaises(PermissionError):
            self.api.positions("wrong")
        self.assertEqual(self.api.positions("abc")[0]["symbol"], "BTC/USDT")
        self.assertEqual(self.api.strategies("abc")[0]["status"], "running")

    def test_command_submission(self) -> None:
        response = self.api.submit_command(
            "abc",
            CommandRequest(action="close", target="spot_perp:BTC/USDT", requested_by="alice"),
        )
        self.assertTrue(response["accepted"])
        self.assertEqual(response["command_id"], "cmd-42")

    def test_create_app_registers_routes(self) -> None:
        app = create_app(self.context)
        route_paths = {route.path for route in app.routes}
        self.assertTrue({"/health", "/positions", "/strategies", "/commands"}.issubset(route_paths))


if __name__ == "__main__":
    unittest.main()
