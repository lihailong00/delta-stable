from __future__ import annotations
import sys
from decimal import Decimal
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from arb.cli import build_parser, main
from arb.settings.exchanges import ExchangeAccountConfig, ExchangeEndpointConfig, ExchangeSettings
from arb.settings.strategies import StrategyConfig, StrategySettings

class TestCli:

    def test_cli_parses_arguments(self) -> None:
        parser = build_parser()
        args = parser.parse_args(['execute', '--strategy', 'spot_perp', '--confirm'])
        assert args.command == 'execute'
        assert args.confirm

    def test_settings_validation(self) -> None:
        strategies = StrategySettings(whitelist={'BTC/USDT'}, strategies={'spot_perp': StrategyConfig(name='spot_perp', min_funding_rate=Decimal('0.0005'))})
        exchanges = ExchangeSettings(exchanges={'binance': ExchangeAccountConfig(name='binance', api_key_env='BINANCE_KEY', api_secret_env='BINANCE_SECRET', endpoints=ExchangeEndpointConfig(rest_base_url='https://api.binance.com', ws_public_url='wss://stream.binance.com/ws'))})
        strategies.validate_config()
        exchanges.validate_config()

    def test_cli_smoke_entrypoint(self) -> None:
        result = main(['scan', '--exchange', 'binance', '--symbol', 'BTC/USDT'])
        assert result['command'] == 'scan'
        assert result['args']['exchange'] == 'binance'

    def test_cli_parses_live_scan_arguments(self) -> None:
        parser = build_parser()
        args = parser.parse_args(['live-scan', '--exchange', 'binance', 'okx', '--symbol', 'BTC/USDT', 'ETH/USDT', '--dry-run', '--iterations', '3'])
        assert args.command == 'live-scan'
        assert args.dry_run
        assert args.iterations == 3

    def test_cli_parses_smoke_arguments_and_dispatches_handler(self) -> None:
        result = main(['smoke', '--exchange', 'binance', 'okx', '--private'], handlers={'smoke': lambda args: {'command': args.command, 'private': args.private, 'exchange': args.exchange}})
        assert result['command'] == 'smoke'
        assert result['private']
        assert result['exchange'] == ['binance', 'okx']

    def test_cli_parses_funding_arb_arguments(self) -> None:
        parser = build_parser()
        args = parser.parse_args(['funding-arb', '--exchange', 'binance', '--symbol', 'BTC/USDT', '--iterations', '2'])
        assert args.command == 'funding-arb'
        assert args.exchange == ['binance']
        assert args.iterations == 2

    def test_cli_dispatches_funding_arb_dry_run_handler(self) -> None:
        result = main(
            ['funding-arb-dry-run', '--exchange', 'binance', '--symbol', 'BTC/USDT'],
            handlers={'funding-arb-dry-run': lambda args: {'command': args.command, 'dry_run': True, 'exchange': args.exchange, 'symbol': args.symbol}},
        )
        assert result['command'] == 'funding-arb-dry-run'
        assert result['dry_run']
        assert result['symbol'] == ['BTC/USDT']
