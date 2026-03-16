from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arb.cli import build_parser, main
from arb.settings.exchanges import ExchangeAccountConfig, ExchangeEndpointConfig, ExchangeSettings
from arb.settings.strategies import StrategyConfig, StrategySettings


class CliTests(unittest.TestCase):
    def test_cli_parses_arguments(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["execute", "--strategy", "spot_perp", "--confirm"])
        self.assertEqual(args.command, "execute")
        self.assertTrue(args.confirm)

    def test_settings_validation(self) -> None:
        strategies = StrategySettings(
            whitelist={"BTC/USDT"},
            strategies={"spot_perp": StrategyConfig(name="spot_perp", min_funding_rate=Decimal("0.0005"))},
        )
        exchanges = ExchangeSettings(
            exchanges={
                "binance": ExchangeAccountConfig(
                    name="binance",
                    api_key_env="BINANCE_KEY",
                    api_secret_env="BINANCE_SECRET",
                    endpoints=ExchangeEndpointConfig(
                        rest_base_url="https://api.binance.com",
                        ws_public_url="wss://stream.binance.com/ws",
                    ),
                )
            }
        )
        strategies.validate()
        exchanges.validate()

    def test_cli_smoke_entrypoint(self) -> None:
        result = main(["scan", "--exchange", "binance", "--symbol", "BTC/USDT"])
        self.assertEqual(result["command"], "scan")
        self.assertEqual(result["args"]["exchange"], "binance")


if __name__ == "__main__":
    unittest.main()
