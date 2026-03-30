"""Dual-mode CLI helpers: headless (JSON) + interactive (rich) utilities."""

from __future__ import annotations

import json
import sys
from typing import Any

import typer
from rich.prompt import Prompt
from rich.text import Text

from autoresearch.marker import MarkerStatus

STATUS_INDICATORS: dict[MarkerStatus, tuple[str, str]] = {
    MarkerStatus.ACTIVE: ("*", "green"),
    MarkerStatus.SKIP: ("o", "dim"),
    MarkerStatus.PAUSED: ("#", "yellow"),
    MarkerStatus.COMPLETED: ("=", "blue"),
    MarkerStatus.NEEDS_HUMAN: ("!", "red"),
}


def is_headless(ctx: typer.Context) -> bool:
    return ctx.obj.get("headless", False) if ctx.obj else False


def headless_output(ctx: typer.Context, data: Any) -> None:
    if is_headless(ctx):
        stream = sys.stderr if isinstance(data, dict) and data.get("status") == "error" else sys.stdout
        print(json.dumps(data, indent=2, default=str), file=stream)


def headless_confirm(
    ctx: typer.Context, message: str, *, default: bool = True
) -> bool:
    if is_headless(ctx):
        return default
    return Prompt.ask(message, choices=["y", "n"], default="y" if default else "n") == "y"


def headless_prompt(
    ctx: typer.Context,
    message: str,
    *,
    flag_value: str | None = None,
    default: str | None = None,
) -> str:
    if is_headless(ctx):
        if flag_value is not None:
            return flag_value
        if default is not None:
            return default
        err_print("Missing required input in headless mode")
        raise typer.Exit(code=2)
    return Prompt.ask(message, default=default)


def render_status(status: MarkerStatus) -> Text:
    indicator, style = STATUS_INDICATORS.get(status, ("?", ""))
    return Text(f"{indicator} {status.value}", style=style)


def err_json(message: str, code: int = 1) -> dict:
    return {"status": "error", "message": message, "code": code}


def ok_json(data: Any = None) -> dict:
    result: dict[str, Any] = {"status": "ok"}
    if data is not None:
        result["data"] = data
    return result


def err_print(message: str) -> None:
    print(json.dumps(err_json(message)), file=sys.stderr)
