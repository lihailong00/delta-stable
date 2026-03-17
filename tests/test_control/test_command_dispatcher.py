from __future__ import annotations
import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from arb.control.audit import AuditLogger
from arb.control.commands import ControlCommand
from arb.control.dispatcher import CommandDispatcher

class TestCommandDispatcher:

    def setup_method(self) -> None:
        self.audit = AuditLogger()
        self.dispatched: list[str] = []
        self.dispatcher = CommandDispatcher(
            lambda command: self.dispatched.append(command.command_id) or {'status': 'done', 'command_id': command.command_id},
            audit=self.audit,
            allowed_users={'alice'},
            confirmation_actions={'close_all', 'manual_open', 'manual_close', 'cancel_workflow'},
        )

    def test_command_idempotence(self) -> None:
        command = ControlCommand(command_id='cmd-1', action='close', target='spot_perp:BTC/USDT', requested_by='alice')
        first = self.dispatcher.submit(command)
        second = self.dispatcher.submit(command)
        assert first['status'] == 'queued'
        assert second['status'] == 'duplicate'

    def test_permissions_whitelist(self) -> None:
        with pytest.raises(PermissionError):
            self.dispatcher.submit(ControlCommand(command_id='cmd-2', action='close', target='x', requested_by='bob'))

    def test_confirmation_flow_and_dispatch(self) -> None:
        command = ControlCommand(command_id='cmd-3', action='manual_open', target='spot_perp:BTC/USDT', requested_by='alice')
        pending = self.dispatcher.submit(command)
        assert pending['status'] == 'pending_confirmation'
        confirmed = self.dispatcher.confirm('cmd-3', 'alice')
        assert confirmed['status'] == 'queued'
        result = self.dispatcher.dispatch_next()
        assert result['status'] == 'done'
        assert self.dispatched == ['cmd-3']

    def test_cancel_pending_command(self) -> None:
        command = ControlCommand(command_id='cmd-5', action='close_all', target='portfolio', requested_by='alice')
        self.dispatcher.submit(command)
        canceled = self.dispatcher.cancel('cmd-5', 'alice')
        assert canceled['status'] == 'canceled'
        assert self.dispatcher.queue_snapshot()['pending_confirmation'] == []

    def test_audit_log_records_actions(self) -> None:
        command = ControlCommand(command_id='cmd-4', action='pause', target='spot_perp:ETH/USDT', requested_by='alice')
        self.dispatcher.submit(command)
        self.dispatcher.dispatch_next()
        outcomes = [record.outcome for record in self.audit.records()]
        assert outcomes == ['queued', 'done']

    def test_dispatch_all_flushes_queue(self) -> None:
        self.dispatcher.submit(ControlCommand(command_id='cmd-6', action='pause', target='spot_perp:BTC/USDT', requested_by='alice'))
        self.dispatcher.submit(ControlCommand(command_id='cmd-7', action='pause', target='spot_perp:ETH/USDT', requested_by='alice'))

        results = self.dispatcher.dispatch_all()

        assert [item['command_id'] for item in results] == ['cmd-6', 'cmd-7']
        assert self.dispatcher.queue_snapshot()['queued'] == []
