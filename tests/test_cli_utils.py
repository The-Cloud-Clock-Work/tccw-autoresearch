"""Tests for cli_utils module."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
import typer

from autoresearch.cli_utils import (
    err_json,
    headless_confirm,
    headless_output,
    headless_prompt,
    is_headless,
    ok_json,
    render_status,
)
from autoresearch.marker import MarkerStatus


class TestIsHeadless:
    def test_true_when_headless(self):
        ctx = MagicMock(spec=typer.Context)
        ctx.obj = {"headless": True}
        assert is_headless(ctx) is True

    def test_false_when_interactive(self):
        ctx = MagicMock(spec=typer.Context)
        ctx.obj = {"headless": False}
        assert is_headless(ctx) is False

    def test_false_when_no_obj(self):
        ctx = MagicMock(spec=typer.Context)
        ctx.obj = None
        assert is_headless(ctx) is False

    def test_false_when_missing_key(self):
        ctx = MagicMock(spec=typer.Context)
        ctx.obj = {}
        assert is_headless(ctx) is False


class TestHeadlessOutput:
    def test_prints_json_when_headless(self, capsys):
        ctx = MagicMock(spec=typer.Context)
        ctx.obj = {"headless": True}
        headless_output(ctx, {"key": "value"})
        output = json.loads(capsys.readouterr().out)
        assert output == {"key": "value"}

    def test_errors_go_to_stderr(self, capsys):
        ctx = MagicMock(spec=typer.Context)
        ctx.obj = {"headless": True}
        headless_output(ctx, {"status": "error", "message": "bad"})
        captured = capsys.readouterr()
        assert captured.out == ""
        output = json.loads(captured.err)
        assert output["status"] == "error"

    def test_noop_when_interactive(self, capsys):
        ctx = MagicMock(spec=typer.Context)
        ctx.obj = {"headless": False}
        headless_output(ctx, {"key": "value"})
        assert capsys.readouterr().out == ""


class TestHeadlessConfirm:
    def test_returns_default_in_headless(self):
        ctx = MagicMock(spec=typer.Context)
        ctx.obj = {"headless": True}
        assert headless_confirm(ctx, "Continue?") is True
        assert headless_confirm(ctx, "Continue?", default=False) is False


class TestHeadlessPrompt:
    def test_returns_flag_value_in_headless(self):
        ctx = MagicMock(spec=typer.Context)
        ctx.obj = {"headless": True}
        assert headless_prompt(ctx, "Enter:", flag_value="abc") == "abc"

    def test_returns_default_in_headless(self):
        ctx = MagicMock(spec=typer.Context)
        ctx.obj = {"headless": True}
        assert headless_prompt(ctx, "Enter:", default="xyz") == "xyz"

    def test_exits_when_no_value_in_headless(self):
        import click
        ctx = MagicMock(spec=typer.Context)
        ctx.obj = {"headless": True}
        with pytest.raises(click.exceptions.Exit):
            headless_prompt(ctx, "Enter:")


class TestRenderStatus:
    def test_all_statuses(self):
        for status in MarkerStatus:
            text = render_status(status)
            assert status.value in text.plain


class TestJsonHelpers:
    def test_err_json(self):
        result = err_json("bad input", 2)
        assert result["status"] == "error"
        assert result["message"] == "bad input"
        assert result["code"] == 2

    def test_ok_json_no_data(self):
        result = ok_json()
        assert result == {"status": "ok"}

    def test_ok_json_with_data(self):
        result = ok_json({"count": 3})
        assert result == {"status": "ok", "data": {"count": 3}}
