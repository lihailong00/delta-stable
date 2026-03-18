from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from arb.bootstrap.live_runtime_factory import resolve_runtime_endpoints
from arb.config.live import load_live_config
from arb.safety.runtime import RuntimeSafety
from arb.settings.exchanges import ExchangeAccountConfig, ExchangeEndpointConfig, ExchangeSettings

class TestLiveRuntimeConfig:

    def test_credentials_and_testnet_switches_validate(self) -> None:
        settings = ExchangeSettings(exchanges={'binance': ExchangeAccountConfig(name='binance', api_key_env='BINANCE_KEY', api_secret_env='BINANCE_SECRET', testnet=True, endpoints=ExchangeEndpointConfig(rest_base_url='https://api.binance.com', ws_public_url='wss://stream.binance.com/ws', testnet_rest_base_url='https://testnet.binance.vision', testnet_ws_public_url='wss://stream.testnet.binance.vision/ws'))})
        settings.validate_config()

    def test_live_config_loads_mode_and_flags(self) -> None:
        config = load_live_config({'ARB_ENV': 'prod', 'ARB_RUNTIME_MODE': 'live', 'ARB_READ_ONLY': 'false', 'ARB_ENABLE_ORDERS': 'true'})
        assert config.env == 'prod'
        assert config.mode == 'live'
        assert not config.use_testnet
        assert not config.read_only
        assert config.orders_enabled

    def test_testnet_endpoint_resolution_uses_testnet_values(self) -> None:
        account = ExchangeAccountConfig(
            name='binance',
            api_key_env='BINANCE_KEY',
            api_secret_env='BINANCE_SECRET',
            endpoints=ExchangeEndpointConfig(
                rest_base_url='https://api.binance.com',
                ws_public_url='wss://stream.binance.com/ws',
                testnet_rest_base_url='https://testnet.binancefuture.com',
                testnet_ws_public_url='wss://stream.testnet.binancefuture.com/ws',
            ),
        )
        config = load_live_config({'ARB_RUNTIME_MODE': 'testnet'})

        resolved = resolve_runtime_endpoints(config=config, account=account)

        assert config.use_testnet
        assert resolved.rest_base_url == 'https://testnet.binancefuture.com'
        assert resolved.ws_public_url == 'wss://stream.testnet.binancefuture.com/ws'

    def test_runtime_safety_blocks_open_orders_when_read_only(self) -> None:
        safety = RuntimeSafety.from_env({'ARB_READ_ONLY': 'true', 'ARB_REDUCE_ONLY': 'false', 'ARB_ENABLE_ORDERS': 'true'})
        assert not safety.can_submit_orders()
        assert not safety.can_open_positions()
        enabled = RuntimeSafety.from_env({'ARB_READ_ONLY': 'false', 'ARB_REDUCE_ONLY': 'true', 'ARB_ENABLE_ORDERS': 'true'})
        assert enabled.can_submit_orders()
        assert not enabled.can_open_positions()
