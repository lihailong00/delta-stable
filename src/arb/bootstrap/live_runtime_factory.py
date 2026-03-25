"""Build live or testnet exchange runtimes from settings and environment."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable, Mapping
from typing import cast

from arb.config.live import LiveRuntimeConfig
from arb.models import MarketType
from arb.net.http import HttpTransport
from arb.net.ws import Connector
from arb.runtime import BinanceRuntime, BitgetRuntime, BybitRuntime, GateRuntime, HtxRuntime, OkxRuntime
from arb.settings.exchanges import ExchangeAccountConfig, ExchangeSettings

type BuiltRuntime = BinanceRuntime | OkxRuntime | BybitRuntime | GateRuntime | BitgetRuntime | HtxRuntime

HttpTransportFactory = Callable[[str], HttpTransport]
WsConnectorFactory = Callable[[str], Connector | None]


@dataclass(slots=True, frozen=True)
class RuntimeEndpointSelection:
    rest_base_url: str
    ws_public_url: str
    ws_private_url: str | None = None


@dataclass(slots=True, frozen=True)
class RuntimeBuildContext:
    exchange: str
    account: ExchangeAccountConfig
    market_type: MarketType
    api_key: str
    api_secret: str
    http_transport: HttpTransport
    ws_connector: Connector | None


@dataclass(slots=True, frozen=True)
class RuntimeSpec:
    builder_method: str
    endpoint_method: str


class LiveRuntimeFactory:
    """Centralize live/testnet runtime assembly for supported exchanges."""

    _RUNTIME_SPECS: dict[str, RuntimeSpec] = {
        "binance": RuntimeSpec("_build_binance_runtime", "_apply_binance_endpoints"),
        "okx": RuntimeSpec("_build_okx_runtime", "_apply_standard_endpoints"),
        "bybit": RuntimeSpec("_build_bybit_runtime", "_apply_standard_endpoints"),
        "gate": RuntimeSpec("_build_gate_runtime", "_apply_standard_endpoints"),
        "bitget": RuntimeSpec("_build_bitget_runtime", "_apply_standard_endpoints"),
        "htx": RuntimeSpec("_build_htx_runtime", "_apply_htx_endpoints"),
    }

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

    def build_all(self, *, market_type: MarketType = MarketType.PERPETUAL) -> dict[str, BuiltRuntime]:
        runtimes: dict[str, BuiltRuntime] = {}
        for name, account in self.settings.enabled_accounts().items():
            runtimes[name] = self.build_one(name, account, market_type=market_type)
        return runtimes

    def build_one(
        self,
        exchange: str,
        account: ExchangeAccountConfig | None = None,
        *,
        market_type: MarketType = MarketType.PERPETUAL,
    ) -> BuiltRuntime:
        config = account or self.settings.exchanges[exchange]
        if not config.enabled:
            raise ValueError(f"exchange {exchange} is disabled")
        spec = self._runtime_spec(exchange)
        selection = self._resolve_endpoints(config)
        context = self._build_context(exchange, config, market_type=market_type)
        runtime = cast(BuiltRuntime, getattr(self, spec.builder_method)(context))
        getattr(self, spec.endpoint_method)(runtime, selection=selection, market_type=market_type)
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

    def _runtime_spec(self, exchange: str) -> RuntimeSpec:
        spec = self._RUNTIME_SPECS.get(exchange)
        if spec is None:
            raise ValueError(f"unsupported exchange runtime: {exchange}")
        return spec

    def _build_context(
        self,
        exchange: str,
        account: ExchangeAccountConfig,
        *,
        market_type: MarketType,
    ) -> RuntimeBuildContext:
        return RuntimeBuildContext(
            exchange=exchange,
            account=account,
            market_type=market_type,
            api_key=self._read_required_env(account.api_key_env, exchange, "api_key"),
            api_secret=self._read_required_env(account.api_secret_env, exchange, "api_secret"),
            http_transport=self.http_transport_factory(exchange),
            ws_connector=self.ws_connector_factory(exchange),
        )

    def _build_binance_runtime(self, context: RuntimeBuildContext) -> BinanceRuntime:
        return BinanceRuntime.build(
            api_key=context.api_key,
            api_secret=context.api_secret,
            market_type=context.market_type,
            http_transport=context.http_transport,
            ws_connector=context.ws_connector,
        )

    def _build_okx_runtime(self, context: RuntimeBuildContext) -> OkxRuntime:
        return OkxRuntime.build(
            api_key=context.api_key,
            api_secret=context.api_secret,
            passphrase=self._read_required_env(context.account.passphrase_env, context.exchange, "passphrase"),
            market_type=context.market_type,
            http_transport=context.http_transport,
            ws_connector=context.ws_connector,
        )

    def _build_bybit_runtime(self, context: RuntimeBuildContext) -> BybitRuntime:
        return BybitRuntime.build(
            api_key=context.api_key,
            api_secret=context.api_secret,
            market_type=context.market_type,
            recv_window=context.account.recv_window,
            http_transport=context.http_transport,
            ws_connector=context.ws_connector,
        )

    def _build_gate_runtime(self, context: RuntimeBuildContext) -> GateRuntime:
        return GateRuntime.build(
            api_key=context.api_key,
            api_secret=context.api_secret,
            http_transport=context.http_transport,
            ws_connector=context.ws_connector,
        )

    def _build_bitget_runtime(self, context: RuntimeBuildContext) -> BitgetRuntime:
        return BitgetRuntime.build(
            api_key=context.api_key,
            api_secret=context.api_secret,
            passphrase=self._read_required_env(context.account.passphrase_env, context.exchange, "passphrase"),
            market_type=context.market_type,
            http_transport=context.http_transport,
            ws_connector=context.ws_connector,
        )

    def _build_htx_runtime(self, context: RuntimeBuildContext) -> HtxRuntime:
        return HtxRuntime.build(
            api_key=context.api_key,
            api_secret=context.api_secret,
            market_type=context.market_type,
            http_transport=context.http_transport,
            ws_connector=context.ws_connector,
        )

    def _apply_binance_endpoints(
        self,
        runtime: BinanceRuntime,
        *,
        selection: RuntimeEndpointSelection,
        market_type: MarketType,
    ) -> None:
        if market_type is MarketType.SPOT:
            runtime.exchange.spot_base_url = selection.rest_base_url
        else:
            runtime.exchange.futures_base_url = selection.rest_base_url
        runtime.ws_client.endpoint = selection.ws_public_url

    def _apply_htx_endpoints(
        self,
        runtime: HtxRuntime,
        *,
        selection: RuntimeEndpointSelection,
        market_type: MarketType,
    ) -> None:
        del market_type
        runtime.exchange.spot_base_url = selection.rest_base_url
        runtime.exchange.swap_base_url = selection.rest_base_url
        runtime.ws_client.endpoint = selection.ws_public_url

    def _apply_standard_endpoints(
        self,
        runtime: OkxRuntime | BybitRuntime | GateRuntime | BitgetRuntime,
        *,
        selection: RuntimeEndpointSelection,
        market_type: MarketType,
    ) -> None:
        del market_type
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
) -> dict[str, BuiltRuntime]:
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
        settings=ExchangeSettings(exchanges={account.name: account}),
        config=config,
        env={},
        http_transport_factory=lambda _: HttpTransport(client=_NullHttpClient()),
    )._resolve_endpoints(account)


class _NullHttpClient:
    async def request(self, *_args: object, **_kwargs: object) -> object:
        raise AssertionError("test helper http client should not be used for network requests")
