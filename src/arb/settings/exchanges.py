"""Exchange settings."""

from __future__ import annotations

from pydantic import Field

from arb.schemas.base import ArbFrozenModel


class ExchangeEndpointConfig(ArbFrozenModel):
    rest_base_url: str
    ws_public_url: str
    ws_private_url: str | None = None
    testnet_rest_base_url: str | None = None
    testnet_ws_public_url: str | None = None
    testnet_ws_private_url: str | None = None

    def resolve_rest_base_url(self, *, use_testnet: bool) -> str:
        if use_testnet:
            if not self.testnet_rest_base_url:
                raise ValueError("missing testnet_rest_base_url")
            return self.testnet_rest_base_url
        return self.rest_base_url

    def resolve_ws_public_url(self, *, use_testnet: bool) -> str:
        if use_testnet:
            if not self.testnet_ws_public_url:
                raise ValueError("missing testnet_ws_public_url")
            return self.testnet_ws_public_url
        return self.ws_public_url

    def resolve_ws_private_url(self, *, use_testnet: bool) -> str | None:
        if use_testnet:
            return self.testnet_ws_private_url or self.testnet_ws_public_url or self.ws_private_url
        return self.ws_private_url


class ExchangeAccountConfig(ArbFrozenModel):
    name: str
    enabled: bool = True
    api_key_env: str | None = None
    api_secret_env: str | None = None
    passphrase_env: str | None = None
    testnet: bool = False
    recv_window: int = 5000
    endpoints: ExchangeEndpointConfig | None = None


class ExchangeSettings(ArbFrozenModel):
    exchanges: dict[str, ExchangeAccountConfig] = Field(default_factory=dict)

    def validate_config(self) -> None:
        for name, config in self.exchanges.items():
            if config.enabled and (not config.api_key_env or not config.api_secret_env):
                raise ValueError(f"exchange {name} is enabled but missing credential env vars")
            if config.enabled and config.endpoints is None:
                raise ValueError(f"exchange {name} is enabled but missing endpoints")
            if config.testnet and config.endpoints is not None:
                if not config.endpoints.testnet_rest_base_url or not config.endpoints.testnet_ws_public_url:
                    raise ValueError(f"exchange {name} testnet is enabled but missing testnet endpoints")

    def enabled_accounts(self) -> dict[str, ExchangeAccountConfig]:
        return {
            name: config
            for name, config in self.exchanges.items()
            if config.enabled
        }
