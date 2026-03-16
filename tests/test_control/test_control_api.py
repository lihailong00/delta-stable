from __future__ import annotations
import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from arb.control.api import ControlAPI, create_app
from arb.control.deps import ApiContext
from arb.control.schemas import CommandRequest

class TestControlApi:

    def setup_method(self) -> None:
        self.context = ApiContext(positions_provider=lambda: [{'exchange': 'binance', 'symbol': 'BTC/USDT', 'market_type': 'spot', 'quantity': '1', 'direction': 'long'}], strategies_provider=lambda: [{'name': 'spot_perp', 'status': 'running'}], command_handler=lambda command: {'accepted': True, 'command_id': 'cmd-42', **command}, auth_token='abc')
        self.api = ControlAPI(self.context)

    def test_health_check(self) -> None:
        assert self.api.health()['status'] == 'ok'

    def test_positions_and_strategies_require_auth(self) -> None:
        with pytest.raises(PermissionError):
            self.api.positions('wrong')
        assert self.api.positions('abc')[0]['symbol'] == 'BTC/USDT'
        assert self.api.strategies('abc')[0]['status'] == 'running'

    def test_command_submission(self) -> None:
        response = self.api.submit_command('abc', CommandRequest(action='close', target='spot_perp:BTC/USDT', requested_by='alice'))
        assert response['accepted']
        assert response['command_id'] == 'cmd-42'

    def test_create_app_registers_routes(self) -> None:
        app = create_app(self.context)
        route_paths = {route.path for route in app.routes}
        assert {'/health', '/positions', '/strategies', '/commands'}.issubset(route_paths)
