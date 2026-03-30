"""Metric extraction, guard verification, and confidence scoring."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from statistics import median


class HarnessError(Exception):
    """Raised when harness execution has a non-recoverable issue."""


@dataclass
class HarnessResult:
    """Result of running a harness command."""

    exit_code: int
    stdout: str
    stderr: str
    metric: float | None  # None = crash (extraction failed)
    log_path: Path


@dataclass
class GuardResult:
    """Result of running a guard command."""

    passed: bool
    value: float | None
    output: str


def run_harness(
    command: str,
    extract: str,
    worktree_path: Path,
    marker_name: str,
    timeout_seconds: int = 600,
) -> HarnessResult:
    """Run a harness command, write run.log, extract metric value.

    Args:
        command: Shell command to run the harness.
        extract: Shell expression to extract a number from output.
        worktree_path: Working directory for the command.
        marker_name: Marker name (for run.log location).
        timeout_seconds: Maximum runtime before killing.

    Returns:
        HarnessResult with extracted metric (None if extraction failed).
    """
    log_dir = worktree_path / ".autoresearch" / marker_name
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "run.log"

    try:
        result = subprocess.run(
            ["bash", "-c", command],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as e:
        partial = ""
        if e.stdout:
            partial += e.stdout if isinstance(e.stdout, str) else e.stdout.decode(errors="replace")
        if e.stderr:
            partial += e.stderr if isinstance(e.stderr, str) else e.stderr.decode(errors="replace")
        log_content = f"TIMEOUT: command exceeded time limit\n{partial}"
        log_path.write_text(log_content, errors="replace")
        return HarnessResult(
            exit_code=-1, stdout="", stderr="TIMEOUT", metric=None, log_path=log_path
        )

    combined = result.stdout + result.stderr
    log_path.write_text(combined, errors="replace")

    metric = _extract_metric(combined, extract, worktree_path)

    return HarnessResult(
        exit_code=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
        metric=metric,
        log_path=log_path,
    )


def run_guard(
    command: str,
    extract: str | None,
    threshold: float | None,
    worktree_path: Path,
    timeout_seconds: int = 600,
) -> GuardResult:
    """Run a guard command and check against threshold.

    If extract and threshold are provided, extracts a value and checks >= threshold.
    Otherwise, uses exit code only (0 = pass).
    """
    try:
        result = subprocess.run(
            ["bash", "-c", command],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return GuardResult(passed=False, value=None, output="TIMEOUT")

    combined = result.stdout + result.stderr

    if extract and threshold is not None:
        value = _extract_metric(combined, extract, worktree_path)
        if value is None:
            return GuardResult(passed=False, value=None, output=combined)
        return GuardResult(passed=value >= threshold, value=value, output=combined)

    return GuardResult(
        passed=result.returncode == 0, value=None, output=combined
    )


def _extract_metric(
    output: str, extract: str, cwd: Path | None = None
) -> float | None:
    """Extract a numeric value from output using a shell expression."""
    try:
        result = subprocess.run(
            ["bash", "-c", f'echo {_shell_quote(output)} | {extract}'],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=cwd,
        )
        text = result.stdout.strip()
        if not text:
            return None
        numbers = re.findall(r"-?(?:\d+\.?\d*|\.\d+)", text)
        if not numbers:
            return None
        return float(numbers[-1])
    except (subprocess.TimeoutExpired, ValueError):
        return None


def _shell_quote(s: str) -> str:
    """Quote a string for safe embedding in a shell command."""
    return "'" + s.replace("'", "'\\''") + "'"


def is_improved(
    current: float, previous: float, direction: str
) -> bool:
    """Check if current metric is strictly better than previous."""
    if direction == "higher":
        return current > previous
    return current < previous


def compute_confidence(
    kept_metrics: list[float], baseline: float, current: float
) -> float | None:
    """Compute MAD-based confidence score.

    Returns None if fewer than 3 kept metrics.
    Formula: |current - baseline| / (MAD * 1.4826)
    """
    if len(kept_metrics) < 3:
        return None

    med = median(kept_metrics)
    deviations = [abs(x - med) for x in kept_metrics]
    mad = median(deviations)

    if mad == 0:
        return None if current == baseline else float("inf")

    return abs(current - baseline) / (mad * 1.4826)


def confidence_label(score: float | None) -> str:
    """Return confidence label: HIGH, MEDIUM, or LOW."""
    if score is None:
        return "--"
    if score >= 2.0:
        return "HIGH"
    if score >= 1.0:
        return "MEDIUM"
    return "LOW"
