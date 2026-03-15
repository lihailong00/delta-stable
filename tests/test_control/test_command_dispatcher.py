from __future__ import annotations

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arb.control.audit import AuditLogger
from arb.control.commands import ControlCommand
from arb.control.dispatcher import CommandDispatcher


class CommandDispatcherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.audit = AuditLogger()
        self.dispatched: list[str] = []
        self.dispatcher = CommandDispatcher(
            lambda command: self.dispatched.append(command.command_id) or {"status": "done", "command_id": command.command_id},
            audit=self.audit,
            allowed_users={"alice"},
            confirmation_actions={"close_all"},
        )

    def test_command_idempotence(self) -> None:
        command = ControlCommand("cmd-1", "close", "spot_perp:BTC/USDT", "alice")
        first = self.dispatcher.submit(command)
        second = self.dispatcher.submit(command)
        self.assertEqual(first["status"], "queued")
        self.assertEqual(second["status"], "duplicate")

    def test_permissions_whitelist(self) -> None:
        with self.assertRaises(PermissionError):
            self.dispatcher.submit(ControlCommand("cmd-2", "close", "x", "bob"))

    def test_confirmation_flow_and_dispatch(self) -> None:
        command = ControlCommand("cmd-3", "close_all", "portfolio", "alice")
        pending = self.dispatcher.submit(command)
        self.assertEqual(pending["status"], "pending_confirmation")
        confirmed = self.dispatcher.confirm("cmd-3", "alice")
        self.assertEqual(confirmed["status"], "queued")
        result = self.dispatcher.dispatch_next()
        self.assertEqual(result["status"], "done")
        self.assertEqual(self.dispatched, ["cmd-3"])

    def test_audit_log_records_actions(self) -> None:
        command = ControlCommand("cmd-4", "pause", "spot_perp:ETH/USDT", "alice")
        self.dispatcher.submit(command)
        self.dispatcher.dispatch_next()
        outcomes = [record.outcome for record in self.audit.records()]
        self.assertEqual(outcomes, ["queued", "done"])


if __name__ == "__main__":
    unittest.main()
