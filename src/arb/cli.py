"""Command line entrypoint."""

from __future__ import annotations

import asyncio
from typing import Annotated

import typer

from arb.bootstrap.schemas import CliParsedResult, CliResult, CommandHandlerMap, cli_args_to_serializable
from arb.cli_support import invoke_typer_app

_OPTION_NAMES = {
    "--exchange",
    "--symbol",
    "--strategy",
    "--confirm",
    "--dataset",
    "--date",
    "--market-type",
    "--iterations",
    "--dry-run",
    "--private",
    "--help",
}
_MULTI_VALUE_OPTIONS = {
    "--exchange",
    "--symbol",
}


def build_app(
    *,
    handlers: CommandHandlerMap | None = None,
) -> typer.Typer:
    app = typer.Typer(
        name="arb",
        add_completion=False,
        no_args_is_help=True,
        pretty_exceptions_enable=False,
    )

    def dispatch(command: str, args: dict[str, object]) -> CliResult:
        payload = cli_args_to_serializable({"command": command, **args})
        if handlers and command in handlers:
            result = handlers[command](payload)
            if asyncio.iscoroutine(result):
                return asyncio.run(result)
            return result
        return CliParsedResult(command=command, args=payload)

    @app.command("scan")
    def scan(
        exchange: Annotated[str | None, typer.Option("--exchange")] = None,
        symbol: Annotated[str | None, typer.Option("--symbol")] = None,
    ) -> CliResult:
        return dispatch("scan", {"exchange": exchange, "symbol": symbol})

    @app.command("execute")
    def execute(
        strategy: Annotated[str, typer.Option("--strategy")],
        confirm: Annotated[bool, typer.Option("--confirm")] = False,
    ) -> CliResult:
        return dispatch("execute", {"strategy": strategy, "confirm": confirm})

    @app.command("backtest")
    def backtest(
        dataset: Annotated[str, typer.Option("--dataset")],
        strategy: Annotated[str, typer.Option("--strategy")],
    ) -> CliResult:
        return dispatch("backtest", {"dataset": dataset, "strategy": strategy})

    @app.command("report")
    def report(
        date: Annotated[str | None, typer.Option("--date")] = None,
    ) -> CliResult:
        return dispatch("report", {"date": date})

    @app.command("live-scan")
    def live_scan(
        exchange: Annotated[list[str], typer.Option("--exchange")],
        symbol: Annotated[list[str], typer.Option("--symbol")],
        market_type: Annotated[str, typer.Option("--market-type")] = "perpetual",
        iterations: Annotated[int, typer.Option("--iterations")] = 1,
        dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    ) -> CliResult:
        return dispatch(
            "live-scan",
            {
                "exchange": exchange,
                "symbol": symbol,
                "market_type": market_type,
                "iterations": iterations,
                "dry_run": dry_run,
            },
        )

    @app.command("smoke")
    def smoke(
        exchange: Annotated[list[str] | None, typer.Option("--exchange")] = None,
        private: Annotated[bool, typer.Option("--private")] = False,
    ) -> CliResult:
        return dispatch("smoke", {"exchange": exchange, "private": private})

    @app.command("funding-arb")
    def funding_arb(
        exchange: Annotated[list[str], typer.Option("--exchange")],
        symbol: Annotated[list[str], typer.Option("--symbol")],
        market_type: Annotated[str, typer.Option("--market-type")] = "perpetual",
        iterations: Annotated[int, typer.Option("--iterations")] = 1,
    ) -> CliResult:
        return dispatch(
            "funding-arb",
            {
                "exchange": exchange,
                "symbol": symbol,
                "market_type": market_type,
                "iterations": iterations,
            },
        )

    @app.command("funding-arb-dry-run")
    def funding_arb_dry_run(
        exchange: Annotated[list[str], typer.Option("--exchange")],
        symbol: Annotated[list[str], typer.Option("--symbol")],
        market_type: Annotated[str, typer.Option("--market-type")] = "perpetual",
        iterations: Annotated[int, typer.Option("--iterations")] = 1,
    ) -> CliResult:
        return dispatch(
            "funding-arb-dry-run",
            {
                "exchange": exchange,
                "symbol": symbol,
                "market_type": market_type,
                "iterations": iterations,
            },
        )

    return app


def main(
    argv: list[str] | None = None,
    *,
    handlers: CommandHandlerMap | None = None,
) -> CliResult:
    return invoke_typer_app(
        build_app(handlers=handlers),
        argv=argv,
        prog_name="arb",
        multi_value_options=_MULTI_VALUE_OPTIONS,
        option_names=_OPTION_NAMES,
        standalone_mode=False,
    )


def run(argv: list[str] | None = None) -> None:
    invoke_typer_app(
        build_app(),
        argv=argv,
        prog_name="arb",
        multi_value_options=_MULTI_VALUE_OPTIONS,
        option_names=_OPTION_NAMES,
        standalone_mode=True,
    )


if __name__ == "__main__":
    run()
