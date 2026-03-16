"""Command line entrypoint."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from typing import Any


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="arb")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser("scan")
    scan.add_argument("--exchange")
    scan.add_argument("--symbol")

    execute = subparsers.add_parser("execute")
    execute.add_argument("--strategy", required=True)
    execute.add_argument("--confirm", action="store_true")

    backtest = subparsers.add_parser("backtest")
    backtest.add_argument("--dataset", required=True)
    backtest.add_argument("--strategy", required=True)

    report = subparsers.add_parser("report")
    report.add_argument("--date")

    live_scan = subparsers.add_parser("live-scan")
    live_scan.add_argument("--exchange", nargs="+", required=True)
    live_scan.add_argument("--symbol", nargs="+", required=True)
    live_scan.add_argument("--market-type", choices=["spot", "perpetual"], default="perpetual")
    live_scan.add_argument("--iterations", type=int, default=1)
    live_scan.add_argument("--dry-run", action="store_true")

    smoke = subparsers.add_parser("smoke")
    smoke.add_argument("--exchange", nargs="+")
    smoke.add_argument("--private", action="store_true")

    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    handlers: dict[str, Any] | None = None,
) -> dict[str, object] | Any:
    parser = build_parser()
    args = parser.parse_args(argv)
    if handlers and args.command in handlers:
        result = handlers[args.command](args)
        if asyncio.iscoroutine(result):
            return asyncio.run(result)
        return result
    return {"command": args.command, "args": vars(args)}


if __name__ == "__main__":
    main()
