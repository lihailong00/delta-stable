from __future__ import annotations

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from arb.config.live import load_live_config
from arb.safety.runtime import RuntimeSafety
from arb.settings.exchanges import ExchangeAccountConfig, ExchangeEndpointConfig, ExchangeSettings


class LiveRuntimeConfigTests(unittest.TestCase):
    def test_credentials_and_testnet_switches_validate(self) -> None:
        settings = ExchangeSettings(
            exchanges={
                "binance": ExchangeAccountConfig(
                    name="binance",
                    api_key_env="BINANCE_KEY",
                    api_secret_env="BINANCE_SECRET",
                    testnet=True,
                    endpoints=ExchangeEndpointConfig(
                        rest_base_url="https://api.binance.com",
                        ws_public_url="wss://stream.binance.com/ws",
                        testnet_rest_base_url="https://testnet.binance.vision",
                        testnet_ws_public_url="wss://stream.testnet.binance.vision/ws",
                    ),
                )
            }
        )
        settings.validate()

    def test_live_config_loads_mode_and_flags(self) -> None:
        config = load_live_config(
            {
                "ARB_ENV": "prod",
                "ARB_RUNTIME_MODE": "live",
                "ARB_READ_ONLY": "false",
                "ARB_ENABLE_ORDERS": "true",
            }
        )
        self.assertEqual(config.env, "prod")
        self.assertEqual(config.mode, "live")
        self.assertFalse(config.read_only)
        self.assertTrue(config.orders_enabled)

    def test_runtime_safety_blocks_open_orders_when_read_only(self) -> None:
        safety = RuntimeSafety.from_env(
            {
                "ARB_READ_ONLY": "true",
                "ARB_REDUCE_ONLY": "false",
                "ARB_ENABLE_ORDERS": "true",
            }
        )
        self.assertFalse(safety.can_submit_orders())
        self.assertFalse(safety.can_open_positions())

        enabled = RuntimeSafety.from_env(
            {
                "ARB_READ_ONLY": "false",
                "ARB_REDUCE_ONLY": "true",
                "ARB_ENABLE_ORDERS": "true",
            }
        )
        self.assertTrue(enabled.can_submit_orders())
        self.assertFalse(enabled.can_open_positions())


if __name__ == "__main__":
    unittest.main()
