from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from arb.settings.exchanges import ExchangeAccountConfig, ExchangeEndpointConfig, ExchangeSettings
from arb.settings.strategies import StrategyConfig, StrategySettings


class TestExchangeSettings:
    def test_enabled_accounts_only_returns_enabled_entries(self) -> None:
        settings = ExchangeSettings(
            exchanges={
                "binance": ExchangeAccountConfig(
                    name="binance",
                    enabled=True,
                    api_key_env="BINANCE_KEY",
                    api_secret_env="BINANCE_SECRET",
                    endpoints=ExchangeEndpointConfig(
                        rest_base_url="https://api.binance.com",
                        ws_public_url="wss://stream.binance.com/ws",
                    ),
                ),
                "okx": ExchangeAccountConfig(name="okx", enabled=False),
            }
        )

        assert list(settings.enabled_accounts()) == ["binance"]

    def test_validate_rejects_enabled_testnet_account_without_testnet_endpoints(self) -> None:
        settings = ExchangeSettings(
            exchanges={
                "binance": ExchangeAccountConfig(
                    name="binance",
                    enabled=True,
                    api_key_env="BINANCE_KEY",
                    api_secret_env="BINANCE_SECRET",
                    testnet=True,
                    endpoints=ExchangeEndpointConfig(
                        rest_base_url="https://api.binance.com",
                        ws_public_url="wss://stream.binance.com/ws",
                    ),
                )
            }
        )

        with pytest.raises(ValueError, match="missing testnet endpoints"):
            settings.validate_config()


class TestStrategySettings:
    def test_validate_rejects_symbol_overlap(self) -> None:
        settings = StrategySettings(whitelist={"BTC/USDT"}, blacklist={"BTC/USDT"})

        with pytest.raises(ValueError, match="both whitelist and blacklist"):
            settings.validate_config()

    def test_validate_rejects_negative_min_funding_rate(self) -> None:
        settings = StrategySettings(
            strategies={
                "spot_perp": StrategyConfig(
                    name="spot_perp",
                    min_funding_rate=Decimal("-0.0001"),
                )
            }
        )

        with pytest.raises(ValueError, match="negative min_funding_rate"):
            settings.validate_config()
