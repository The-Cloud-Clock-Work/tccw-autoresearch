"""Telemetry: parse stream-json output from Claude CLI."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TelemetryReport:
    session_id: str | None = None
    model: str | None = None
    permission_mode: str | None = None

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0

    total_cost_usd: float = 0.0

    duration_ms: int = 0
    duration_api_ms: int = 0
    num_turns: int = 0

    tools_available: list[str] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)
    tool_calls: int = 0

    permission_denials: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    stop_reason: str | None = None
    is_error: bool = False
    result_text: str | None = None


def parse_stream_json(output: str) -> TelemetryReport:
    """Parse stream-json output from claude CLI into a structured report."""
    report = TelemetryReport()

    for line in output.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        event_type = event.get("type")

        if event_type == "system" and event.get("subtype") == "init":
            report.session_id = event.get("session_id")
            report.model = event.get("model")
            report.permission_mode = event.get("permissionMode")
            report.tools_available = event.get("tools", [])

        elif event_type == "assistant":
            msg = event.get("message", {})
            for block in msg.get("content", []):
                if block.get("type") == "tool_use":
                    tool_name = block.get("name", "")
                    report.tool_calls += 1
                    if tool_name and tool_name not in report.tools_used:
                        report.tools_used.append(tool_name)
            usage = msg.get("usage", {})
            report.input_tokens += usage.get("input_tokens", 0)
            report.output_tokens += usage.get("output_tokens", 0)
            report.cache_read_tokens += usage.get("cache_read_input_tokens", 0)
            report.cache_creation_tokens += usage.get("cache_creation_input_tokens", 0)

        elif event_type == "result":
            report.total_cost_usd = event.get("total_cost_usd", 0.0)
            report.duration_ms = event.get("duration_ms", 0)
            report.duration_api_ms = event.get("duration_api_ms", 0)
            report.num_turns = event.get("num_turns", 0)
            report.stop_reason = event.get("stop_reason")
            report.is_error = event.get("is_error", False)
            report.result_text = event.get("result")
            report.permission_denials = event.get("permission_denials", [])

    return report


def extract_description_from_telemetry(report: TelemetryReport) -> str | None:
    """Extract experiment description from telemetry result text."""
    if not report.result_text:
        return None
    for line in report.result_text.strip().splitlines():
        stripped = line.strip()
        if stripped and len(stripped) >= 3:
            return stripped[:200]
    return None


def save_telemetry_report(report: TelemetryReport, logs_dir: Path, timestamp: str) -> Path:
    """Save telemetry report as JSON."""
    report_path = logs_dir / f"telemetry-{timestamp}.json"
    data = {
        "session_id": report.session_id,
        "model": report.model,
        "tokens": {
            "input": report.input_tokens,
            "output": report.output_tokens,
            "cache_read": report.cache_read_tokens,
            "cache_creation": report.cache_creation_tokens,
        },
        "cost_usd": report.total_cost_usd,
        "duration_ms": report.duration_ms,
        "num_turns": report.num_turns,
        "tools_used": report.tools_used,
        "tool_calls": report.tool_calls,
        "permission_denials": report.permission_denials,
        "errors": report.errors,
        "stop_reason": report.stop_reason,
        "is_error": report.is_error,
    }
    report_path.write_text(json.dumps(data, indent=2))
    return report_path
