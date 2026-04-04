"""Auto-merge gate chain — deterministic validation before merge."""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from autoresearch.engine import RunResult
    from autoresearch.marker import Marker

logger = logging.getLogger(__name__)


@dataclass
class GateResult:
    """Result of a single gate check."""

    name: str
    passed: bool
    reason: str
    value: str | None = None


@dataclass
class GateChainResult:
    """Result of running the full gate chain."""

    all_passed: bool
    gates: list[GateResult] = field(default_factory=list)

    def summary(self) -> str:
        parts = []
        for g in self.gates:
            symbol = "✓" if g.passed else "✗"
            val = f" ({g.value})" if g.value else ""
            parts.append(f"{g.name} {symbol}{val}")
        return " | ".join(parts)


def _run_command(command: str, cwd: Path | None = None, timeout: int = 300) -> tuple[int, str]:
    """Run a shell command, return (exit_code, output)."""
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=timeout,
        )
        output = (result.stdout + result.stderr).strip()
        return result.returncode, output
    except subprocess.TimeoutExpired:
        return 1, f"timeout after {timeout}s"
    except Exception as e:
        return 1, str(e)


def gate_metric_improved(
    repo_path: Path, marker: Marker, run_result: RunResult
) -> GateResult:
    """Gate 1: at least one experiment was kept."""
    if run_result.kept > 0:
        return GateResult(
            name="metric",
            passed=True,
            reason=f"{run_result.kept} experiments kept",
            value=str(run_result.final_metric),
        )
    return GateResult(
        name="metric",
        passed=False,
        reason="no experiments kept",
        value="0 kept",
    )


def gate_quality_gate(
    repo_path: Path, marker: Marker, run_result: RunResult
) -> GateResult:
    """Gate 2: quality gate passes (uses marker.guard.command)."""
    if not marker.guard.command:
        return GateResult(name="quality_gate", passed=True, reason="no guard configured")

    exit_code, output = _run_command(marker.guard.command, cwd=repo_path)
    if exit_code == 0:
        return GateResult(name="quality_gate", passed=True, reason="quality gate OK", value="PASS")
    return GateResult(
        name="quality_gate",
        passed=False,
        reason=output[:200],
        value="FAIL",
    )


def gate_security(
    repo_path: Path, marker: Marker, run_result: RunResult
) -> GateResult:
    """Gate 3: zero vulnerabilities + acceptable security rating."""
    auto_merge = getattr(marker, "auto_merge", None)
    cmd = getattr(auto_merge, "security_command", None) if auto_merge else None

    if not cmd:
        return GateResult(name="security", passed=True, reason="no security gate configured")

    exit_code, output = _run_command(cmd, cwd=repo_path)
    if exit_code == 0:
        return GateResult(name="security", passed=True, reason="security OK", value="PASS")
    return GateResult(
        name="security",
        passed=False,
        reason=output[:200],
        value="FAIL",
    )


def gate_tests(
    repo_path: Path, marker: Marker, run_result: RunResult
) -> GateResult:
    """Gate 4: project test suite passes."""
    auto_merge = getattr(marker, "auto_merge", None)
    cmd = getattr(auto_merge, "test_command", None) if auto_merge else None

    if not cmd:
        return GateResult(name="tests", passed=True, reason="no test command configured")

    exit_code, output = _run_command(cmd, cwd=repo_path, timeout=600)
    if exit_code == 0:
        return GateResult(name="tests", passed=True, reason="tests passed", value="PASS")
    return GateResult(
        name="tests",
        passed=False,
        reason=output[-200:],
        value="FAIL",
    )


def gate_confidence(
    repo_path: Path, marker: Marker, run_result: RunResult
) -> GateResult:
    """Gate 5: statistical confidence meets minimum threshold."""
    auto_merge = getattr(marker, "auto_merge", None)
    min_conf = getattr(auto_merge, "min_confidence", 1.0) if auto_merge else 1.0

    if run_result.final_confidence is None:
        return GateResult(
            name="confidence",
            passed=True,
            reason="< 3 keeps, confidence not computable — skipped",
            value="--",
        )

    if run_result.final_confidence >= min_conf:
        return GateResult(
            name="confidence",
            passed=True,
            reason=f"confidence {run_result.final_confidence:.2f} >= {min_conf}",
            value=f"{run_result.final_confidence:.2f}",
        )
    return GateResult(
        name="confidence",
        passed=False,
        reason=f"confidence {run_result.final_confidence:.2f} < {min_conf}",
        value=f"{run_result.final_confidence:.2f}",
    )


BUILTIN_GATES = {
    "metric": gate_metric_improved,
    "quality_gate": gate_quality_gate,
    "security": gate_security,
    "tests": gate_tests,
    "confidence": gate_confidence,
}


def run_gate_chain(
    repo_path: Path,
    marker: Marker,
    run_result: RunResult,
    gate_names: list[str] | None = None,
) -> GateChainResult:
    """Run gates in sequence. Short-circuits on first failure."""
    if gate_names is None:
        auto_merge = getattr(marker, "auto_merge", None)
        gate_names = getattr(auto_merge, "gates", list(BUILTIN_GATES.keys())) if auto_merge else list(BUILTIN_GATES.keys())

    results: list[GateResult] = []

    for name in gate_names:
        gate_fn = BUILTIN_GATES.get(name)
        if not gate_fn:
            logger.warning(f"Unknown gate: {name}")
            continue

        result = gate_fn(repo_path, marker, run_result)
        results.append(result)
        logger.info(f"Gate {result.name}: {'PASS' if result.passed else 'FAIL'} — {result.reason}")

        if not result.passed:
            return GateChainResult(all_passed=False, gates=results)

    return GateChainResult(all_passed=True, gates=results)
