"""Build live or testnet exchange runtimes from settings and environment."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from arb.config.live import LiveRuntimeConfig
from arb.models import MarketType
from arb.net.http import HttpTransport
from arb.runtime import BinanceRuntime, BitgetRuntime, BybitRuntime, GateRuntime, HtxRuntime, OkxRuntime
from arb.settings.exchanges import ExchangeAccountConfig, ExchangeEndpointConfig, ExchangeSettings

HttpTransportFactory = Callable[[str], HttpTransport]
WsConnectorFactory = Callable[[str], Any]


@dataclass(slots=True, frozen=True)
class RuntimeEndpointSelection:
    rest_base_url: str
    ws_public_url: str
    ws_private_url: str | None = None


class LiveRuntimeFactory:
    """Centralize live/testnet runtime assembly for supported exchanges."""

    def __init__(
        self,
        *,
        settings: ExchangeSettings,
        config: LiveRuntimeConfig,
        env: Mapping[str, str],
        http_transport_factory: HttpTransportFactory | None = None,
        ws_connector_factory: WsConnectorFactory | None = None,
    ) -> None:
        self.settings = settings
        self.config = config
        self.env = env
        self.http_transport_factory = http_transport_factory or (lambda _: HttpTransport())
        self.ws_connector_factory = ws_connector_factory or (lambda _: None)

    def build_all(self, *, market_type: MarketType = MarketType.PERPETUAL) -> dict[str, Any]:
        runtimes: dict[str, Any] = {}
        for name, account in self.settings.enabled_accounts().items():
            runtimes[name] = self.build_one(name, account, market_type=market_type)
        return runtimes

    def build_one(
        self,
        exchange: str,
        account: ExchangeAccountConfig | None = None,
        *,
        market_type: MarketType = MarketType.PERPETUAL,
    ) -> Any:
        config = account or self.settings.exchanges[exchange]
        if not config.enabled:
            raise ValueError(f"exchange {exchange} is disabled")
        selection = self._resolve_endpoints(config)
        api_key = self._read_required_env(config.api_key_env, exchange, "api_key")
        api_secret = self._read_required_env(config.api_secret_env, exchange, "api_secret")
        http_transport = self.http_transport_factory(exchange)
        ws_connector = self.ws_connector_factory(exchange)

        if exchange == "binance":
            runtime = BinanceRuntime.build(
                api_key=api_key,
                api_secret=api_secret,
                market_type=market_type,
                http_transport=http_transport,
                ws_connector=ws_connector,
            )
        elif exchange == "okx":
            runtime = OkxRuntime.build(
                api_key=api_key,
                api_secret=api_secret,
                passphrase=self._read_required_env(config.passphrase_env, exchange, "passphrase"),
                market_type=market_type,
                http_transport=http_transport,
                ws_connector=ws_connector,
            )
        elif exchange == "bybit":
            runtime = BybitRuntime.build(
                api_key=api_key,
                api_secret=api_secret,
                market_type=market_type,
                recv_window=config.recv_window,
                http_transport=http_transport,
                ws_connector=ws_connector,
            )
        elif exchange == "gate":
            runtime = GateRuntime.build(
                api_key=api_key,
                api_secret=api_secret,
                http_transport=http_transport,
                ws_connector=ws_connector,
            )
        elif exchange == "bitget":
            runtime = BitgetRuntime.build(
                api_key=api_key,
                api_secret=api_secret,
                passphrase=self._read_required_env(config.passphrase_env, exchange, "passphrase"),
                market_type=market_type,
                http_transport=http_transport,
                ws_connector=ws_connector,
            )
        elif exchange == "htx":
            runtime = HtxRuntime.build(
                api_key=api_key,
                api_secret=api_secret,
                market_type=market_type,
                http_transport=http_transport,
                ws_connector=ws_connector,
            )
        else:
            raise ValueError(f"unsupported exchange runtime: {exchange}")

        self._apply_endpoints(runtime, exchange=exchange, selection=selection, market_type=market_type)
        return runtime

    def _resolve_endpoints(self, account: ExchangeAccountConfig) -> RuntimeEndpointSelection:
        endpoints = account.endpoints
        if endpoints is None:
            raise ValueError(f"exchange {account.name} is missing endpoints")
        use_testnet = self.config.use_testnet or account.testnet
        return RuntimeEndpointSelection(
            rest_base_url=endpoints.resolve_rest_base_url(use_testnet=use_testnet),
            ws_public_url=endpoints.resolve_ws_public_url(use_testnet=use_testnet),
            ws_private_url=endpoints.resolve_ws_private_url(use_testnet=use_testnet),
        )

    def _read_required_env(self, env_name: str | None, exchange: str, field_name: str) -> str:
        if not env_name:
            raise ValueError(f"exchange {exchange} missing env name for {field_name}")
        value = self.env.get(env_name)
        if not value:
            raise ValueError(f"exchange {exchange} missing env value for {env_name}")
        return value

    def _apply_endpoints(
        self,
        runtime: Any,
        *,
        exchange: str,
        selection: RuntimeEndpointSelection,
        market_type: MarketType,
    ) -> None:
        if exchange == "binance":
            if market_type is MarketType.SPOT:
                runtime.exchange.spot_base_url = selection.rest_base_url
            else:
                runtime.exchange.futures_base_url = selection.rest_base_url
            runtime.ws_client.endpoint = selection.ws_public_url
            return

        if exchange == "htx":
            runtime.exchange.spot_base_url = selection.rest_base_url
            runtime.exchange.swap_base_url = selection.rest_base_url
            runtime.ws_client.endpoint = selection.ws_public_url
            return

        runtime.exchange.base_url = selection.rest_base_url
        if hasattr(runtime, "ws_client"):
            runtime.ws_client.endpoint = selection.ws_public_url
        if hasattr(runtime, "public_ws_client"):
            runtime.public_ws_client.endpoint = selection.ws_public_url
        if hasattr(runtime, "private_ws_client") and selection.ws_private_url:
            runtime.private_ws_client.endpoint = selection.ws_private_url
        if hasattr(runtime, "private_session") and selection.ws_private_url:
            runtime.private_session.endpoint = selection.ws_private_url


def build_live_runtimes(
    *,
    settings: ExchangeSettings,
    env: Mapping[str, str],
    config: LiveRuntimeConfig | None = None,
    market_type: MarketType = MarketType.PERPETUAL,
    http_transport_factory: HttpTransportFactory | None = None,
    ws_connector_factory: WsConnectorFactory | None = None,
) -> dict[str, Any]:
    factory = LiveRuntimeFactory(
        settings=settings,
        config=config or LiveRuntimeConfig.from_env(env),
        env=env,
        http_transport_factory=http_transport_factory,
        ws_connector_factory=ws_connector_factory,
    )
    return factory.build_all(market_type=market_type)


def resolve_runtime_endpoints(
    *,
    config: LiveRuntimeConfig,
    account: ExchangeAccountConfig,
) -> RuntimeEndpointSelection:
    return LiveRuntimeFactory(
        settings=ExchangeSettings({account.name: account}),
        config=config,
        env={},
        http_transport_factory=lambda _: HttpTransport(client=_NullHttpClient()),
    )._resolve_endpoints(account)


class _NullHttpClient:
    async def request(self, *_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("test helper http client should not be used for network requests")
