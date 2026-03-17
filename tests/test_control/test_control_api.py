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
        self.context = ApiContext(
            positions_provider=lambda: [{'exchange': 'binance', 'symbol': 'BTC/USDT', 'market_type': 'spot', 'quantity': '1', 'direction': 'long'}],
            strategies_provider=lambda: [{'name': 'spot_perp', 'status': 'running'}],
            orders_provider=lambda: [{'exchange': 'binance', 'symbol': 'BTC/USDT', 'market_type': 'perpetual', 'order_id': 'ord-1', 'status': 'new', 'filled_quantity': '0'}],
            workflows_provider=lambda: [{'workflow_id': 'wf-1', 'workflow_type': 'funding_spot_perp', 'exchange': 'binance', 'symbol': 'BTC/USDT', 'status': 'opening', 'payload': {'step': 'submit'}}],
            command_handler=lambda command: {'accepted': True, 'command_id': 'cmd-42', 'status': 'pending_confirmation', **command},
            command_confirmer=lambda command_id, actor: {'accepted': True, 'command_id': command_id, 'status': 'queued', 'requested_by': actor},
            command_canceller=lambda command_id, actor: {'accepted': True, 'command_id': command_id, 'status': 'canceled', 'requested_by': actor},
            auth_token='abc',
        )
        self.api = ControlAPI(self.context)

    def test_health_check(self) -> None:
        assert self.api.health()['status'] == 'ok'

    def test_positions_and_strategies_require_auth(self) -> None:
        with pytest.raises(PermissionError):
            self.api.positions('wrong')
        assert self.api.positions('abc')[0]['symbol'] == 'BTC/USDT'
        assert self.api.strategies('abc')[0]['status'] == 'running'
        assert self.api.orders('abc')[0]['order_id'] == 'ord-1'
        assert self.api.workflows('abc')[0]['workflow_id'] == 'wf-1'

    def test_command_submission(self) -> None:
        response = self.api.submit_command('abc', CommandRequest(action='close', target='spot_perp:BTC/USDT', requested_by='alice'))
        assert response['accepted']
        assert response['command_id'] == 'cmd-42'
        assert response['status'] == 'pending_confirmation'

    def test_confirm_and_cancel_commands(self) -> None:
        assert self.api.confirm_command('abc', 'cmd-42', 'alice')['status'] == 'queued'
        assert self.api.cancel_command('abc', 'cmd-42', 'alice')['status'] == 'canceled'

    def test_create_app_registers_routes(self) -> None:
        app = create_app(self.context)
        route_paths = {route.path for route in app.routes}
        assert {'/health', '/positions', '/strategies', '/orders', '/workflows', '/commands', '/commands/{command_id}/confirm', '/commands/{command_id}/cancel'}.issubset(route_paths)
