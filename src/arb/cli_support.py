"""Shared helpers for Typer-based CLI entrypoints."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from typing import Any

import typer
from typer.main import get_command


def normalize_multi_value_options(
    argv: Sequence[str],
    *,
    multi_value_options: set[str],
    option_names: set[str],
) -> list[str]:
    """Expand legacy `--opt a b` syntax into repeated Click/Typer options."""

    normalized: list[str] = []
    index = 0
    while index < len(argv):
        token = argv[index]
        if token not in multi_value_options:
            normalized.append(token)
            index += 1
            continue

        index += 1
        values: list[str] = []
        while index < len(argv):
            candidate = argv[index]
            if candidate in option_names:
                break
            values.append(candidate)
            index += 1

        if not values:
            normalized.append(token)
            continue

        for value in values:
            normalized.extend((token, value))

    return normalized


def invoke_typer_app(
    app: typer.Typer,
    *,
    argv: Sequence[str] | None,
    prog_name: str,
    multi_value_options: set[str] | None = None,
    option_names: set[str] | None = None,
    standalone_mode: bool,
) -> Any:
    """Invoke a Typer app programmatically with optional argv normalization."""

    raw_argv = list(sys.argv[1:] if argv is None else argv)
    normalized_argv = (
        normalize_multi_value_options(
            raw_argv,
            multi_value_options=multi_value_options,
            option_names=option_names or multi_value_options,
        )
        if multi_value_options
        else raw_argv
    )
    command = get_command(app)
    return command.main(
        args=normalized_argv,
        prog_name=prog_name,
        standalone_mode=standalone_mode,
    )
