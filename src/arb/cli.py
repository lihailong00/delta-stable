"""Command line entrypoint."""

from __future__ import annotations

import argparse
from collections.abc import Sequence


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

    return parser


def main(argv: Sequence[str] | None = None) -> dict[str, object]:
    parser = build_parser()
    args = parser.parse_args(argv)
    return {"command": args.command, "args": vars(args)}


if __name__ == "__main__":
    main()
