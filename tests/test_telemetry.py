"""Tests for telemetry parsing."""

from __future__ import annotations

import json
from pathlib import Path

from autoresearch.telemetry import (
    TelemetryReport,
    extract_description_from_telemetry,
    parse_stream_json,
    save_telemetry_report,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "stream_json_sample.jsonl"


class TestParseStreamJson:
    def test_parses_fixture(self):
        output = FIXTURE_PATH.read_text()
        report = parse_stream_json(output)
        assert report.session_id == "abc-123"
        assert report.model == "claude-sonnet-4-6"
        assert report.permission_mode == "bypassPermissions"

    def test_accumulates_tokens(self):
        output = FIXTURE_PATH.read_text()
        report = parse_stream_json(output)
        assert report.input_tokens == 500 + 200 + 300 + 150  # 1150
        assert report.output_tokens == 50 + 30 + 40 + 20  # 140

    def test_extracts_tool_use(self):
        output = FIXTURE_PATH.read_text()
        report = parse_stream_json(output)
        assert report.tool_calls == 3
        assert "Read" in report.tools_used
        assert "Edit" in report.tools_used
        assert "Bash" in report.tools_used

    def test_extracts_result(self):
        output = FIXTURE_PATH.read_text()
        report = parse_stream_json(output)
        assert report.total_cost_usd == 0.015
        assert report.duration_ms == 45000
        assert report.num_turns == 5
        assert report.stop_reason == "end_turn"
        assert report.is_error is False

    def test_extracts_permission_denials(self):
        output = FIXTURE_PATH.read_text()
        report = parse_stream_json(output)
        assert len(report.permission_denials) == 1
        assert "engine.py" in report.permission_denials[0]

    def test_empty_input(self):
        report = parse_stream_json("")
        assert report.session_id is None
        assert report.input_tokens == 0
        assert report.tool_calls == 0

    def test_malformed_lines_skipped(self):
        output = "not json\n{invalid\n"
        report = parse_stream_json(output)
        assert report.session_id is None

    def test_tools_available(self):
        output = FIXTURE_PATH.read_text()
        report = parse_stream_json(output)
        assert "Read" in report.tools_available
        assert "Edit" in report.tools_available


class TestExtractDescription:
    def test_from_result_text(self):
        report = TelemetryReport(result_text="Added edge case test for empty input.")
        desc = extract_description_from_telemetry(report)
        assert desc == "Added edge case test for empty input."

    def test_empty_result(self):
        report = TelemetryReport(result_text=None)
        assert extract_description_from_telemetry(report) is None

    def test_multiline_takes_first(self):
        report = TelemetryReport(result_text="First line\nSecond line")
        desc = extract_description_from_telemetry(report)
        assert desc == "First line"

    def test_truncates_long_text(self):
        report = TelemetryReport(result_text="x" * 300)
        desc = extract_description_from_telemetry(report)
        assert len(desc) == 200


class TestSaveTelemetryReport:
    def test_writes_valid_json(self, tmp_path):
        report = TelemetryReport(
            session_id="test-123",
            model="sonnet",
            input_tokens=1000,
            output_tokens=200,
            total_cost_usd=0.01,
            tool_calls=5,
            tools_used=["Read", "Edit"],
        )
        path = save_telemetry_report(report, tmp_path, "20260331-010000")
        data = json.loads(path.read_text())
        assert data["session_id"] == "test-123"
        assert data["tokens"]["input"] == 1000
        assert data["cost_usd"] == 0.01
        assert data["tools_used"] == ["Read", "Edit"]

    def test_filename_contains_timestamp(self, tmp_path):
        report = TelemetryReport()
        path = save_telemetry_report(report, tmp_path, "20260331-010000")
        assert "telemetry-20260331-010000" in path.name
