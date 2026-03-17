from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arb.bootstrap.live_runtime_factory import build_live_runtimes
from arb.config.live import LiveRuntimeConfig
from arb.models import MarketType
from arb.net.http import HttpTransport
from arb.runtime import BinanceRuntime, OkxRuntime
from arb.settings.exchanges import ExchangeAccountConfig, ExchangeEndpointConfig, ExchangeSettings


class _HttpClient:
    async def request(self, *_args, **_kwargs):
        return {}


class TestLiveRuntimeFactory:
    def test_factory_builds_testnet_runtime_with_overridden_endpoints(self) -> None:
        settings = ExchangeSettings(
            exchanges={
                "binance": ExchangeAccountConfig(
                    name="binance",
                    api_key_env="BINANCE_KEY",
                    api_secret_env="BINANCE_SECRET",
                    endpoints=ExchangeEndpointConfig(
                        rest_base_url="https://api.binance.com",
                        ws_public_url="wss://stream.binance.com/ws",
                        testnet_rest_base_url="https://testnet.binancefuture.com",
                        testnet_ws_public_url="wss://stream.testnet.binancefuture.com/ws",
                    ),
                )
            }
        )
        runtimes = build_live_runtimes(
            settings=settings,
            env={"BINANCE_KEY": "key", "BINANCE_SECRET": "secret"},
            config=LiveRuntimeConfig(mode="testnet"),
            market_type=MarketType.PERPETUAL,
            http_transport_factory=lambda _: HttpTransport(client=_HttpClient()),
            ws_connector_factory=lambda _: None,
        )

        runtime = runtimes["binance"]
        assert isinstance(runtime, BinanceRuntime)
        assert runtime.exchange.futures_base_url == "https://testnet.binancefuture.com"
        assert runtime.ws_client.endpoint == "wss://stream.testnet.binancefuture.com/ws"

    def test_factory_builds_private_runtime_with_passphrase(self) -> None:
        settings = ExchangeSettings(
            exchanges={
                "okx": ExchangeAccountConfig(
                    name="okx",
                    api_key_env="OKX_KEY",
                    api_secret_env="OKX_SECRET",
                    passphrase_env="OKX_PASSPHRASE",
                    endpoints=ExchangeEndpointConfig(
                        rest_base_url="https://www.okx.com",
                        ws_public_url="wss://ws.okx.com/public",
                        ws_private_url="wss://ws.okx.com/private",
                        testnet_rest_base_url="https://testnet.okx.com",
                        testnet_ws_public_url="wss://wspap.okx.com/public",
                        testnet_ws_private_url="wss://wspap.okx.com/private",
                    ),
                )
            }
        )
        runtimes = build_live_runtimes(
            settings=settings,
            env={
                "OKX_KEY": "key",
                "OKX_SECRET": "secret",
                "OKX_PASSPHRASE": "passphrase",
            },
            config=LiveRuntimeConfig(mode="live"),
            market_type=MarketType.PERPETUAL,
            http_transport_factory=lambda _: HttpTransport(client=_HttpClient()),
            ws_connector_factory=lambda _: None,
        )

        runtime = runtimes["okx"]
        assert isinstance(runtime, OkxRuntime)
        assert runtime.exchange.base_url == "https://www.okx.com"
        assert runtime.public_ws_client.endpoint == "wss://ws.okx.com/public"
        assert runtime.private_ws_client.endpoint == "wss://ws.okx.com/private"

    def test_factory_rejects_missing_credentials(self) -> None:
        settings = ExchangeSettings(
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

        try:
            build_live_runtimes(
                settings=settings,
                env={"BINANCE_KEY": "key"},
                config=LiveRuntimeConfig(mode="live"),
                http_transport_factory=lambda _: HttpTransport(client=_HttpClient()),
                ws_connector_factory=lambda _: None,
            )
        except ValueError as exc:
            assert "BINANCE_SECRET" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("expected missing credential error")
