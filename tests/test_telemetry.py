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

    def test_permission_denials_saved(self, tmp_path):
        report = TelemetryReport(permission_denials=["src/engine.py", "src/cli.py"])
        path = save_telemetry_report(report, tmp_path, "ts1")
        data = json.loads(path.read_text())
        assert len(data["permission_denials"]) == 2

    def test_is_error_saved(self, tmp_path):
        report = TelemetryReport(is_error=True)
        path = save_telemetry_report(report, tmp_path, "ts2")
        data = json.loads(path.read_text())
        assert data["is_error"] is True

    def test_stop_reason_saved(self, tmp_path):
        report = TelemetryReport(stop_reason="end_turn")
        path = save_telemetry_report(report, tmp_path, "ts3")
        data = json.loads(path.read_text())
        assert data["stop_reason"] == "end_turn"


class TestParseStreamJsonExtra:
    def test_duplicate_tool_not_duplicated_in_used(self):
        """Same tool_use name used twice → tools_used has it only once."""
        events = [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Read"},
                {"type": "tool_use", "name": "Read"},
            ], "usage": {}}},
        ]
        output = "\n".join(json.dumps(e) for e in events)
        report = parse_stream_json(output)
        assert report.tools_used.count("Read") == 1
        assert report.tool_calls == 2

    def test_cache_tokens_accumulated(self):
        events = [
            {"type": "assistant", "message": {"content": [], "usage": {
                "input_tokens": 100,
                "output_tokens": 10,
                "cache_read_input_tokens": 500,
                "cache_creation_input_tokens": 200,
            }}},
        ]
        output = "\n".join(json.dumps(e) for e in events)
        report = parse_stream_json(output)
        assert report.cache_read_tokens == 500
        assert report.cache_creation_tokens == 200

    def test_result_event_is_error(self):
        events = [
            {"type": "result", "is_error": True, "stop_reason": "error",
             "total_cost_usd": 0.0, "duration_ms": 100, "duration_api_ms": 50,
             "num_turns": 1, "permission_denials": []},
        ]
        output = "\n".join(json.dumps(e) for e in events)
        report = parse_stream_json(output)
        assert report.is_error is True
        assert report.stop_reason == "error"

    def test_blank_lines_ignored(self):
        events = [
            {"type": "result", "is_error": False, "total_cost_usd": 0.005,
             "duration_ms": 1000, "duration_api_ms": 900, "num_turns": 2,
             "stop_reason": "end_turn", "permission_denials": []},
        ]
        output = "\n\n" + "\n".join(json.dumps(e) for e in events) + "\n\n"
        report = parse_stream_json(output)
        assert report.total_cost_usd == 0.005

    def test_unknown_event_type_ignored(self):
        events = [
            {"type": "unknown_event", "data": "something"},
        ]
        output = "\n".join(json.dumps(e) for e in events)
        report = parse_stream_json(output)
        assert report.session_id is None
        assert report.tool_calls == 0


class TestExtractDescriptionExtra:
    def test_whitespace_only_lines_skipped(self):
        report = TelemetryReport(result_text="\n   \n\nActual description")
        desc = extract_description_from_telemetry(report)
        assert desc == "Actual description"

    def test_short_lines_skipped(self):
        report = TelemetryReport(result_text="ab\nLong enough description")
        desc = extract_description_from_telemetry(report)
        assert desc == "Long enough description"

    def test_empty_string_result(self):
        report = TelemetryReport(result_text="")
        assert extract_description_from_telemetry(report) is None
