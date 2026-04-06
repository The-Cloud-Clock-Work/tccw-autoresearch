"""Tests for the auto-merge gate chain."""

from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch


from autoresearch.gates import (
    GateChainResult,
    GateResult,
    gate_confidence,
    gate_metric_improved,
    gate_quality_gate,
    gate_security,
    gate_tests,
    run_gate_chain,
)
from autoresearch.marker import AgentConfig, AutoMerge, Guard, Marker, Metric, MetricDirection, Target


@dataclass
class FakeRunResult:
    marker_name: str = "test"
    experiments: int = 5
    kept: int = 3
    discarded: int = 2
    crashed: int = 0
    final_metric: float | None = 10.0
    final_confidence: float | None = 1.5
    final_status: str = "budget_exhausted"
    branch: str = "autoresearch/test"
    worktree_path: str = "/tmp/test"


def _make_marker(**overrides) -> Marker:
    defaults = {
        "name": "test",
        "target": Target(mutable=["src/**/*.py"]),
        "metric": Metric(command="echo 10", extract="cat", direction=MetricDirection.LOWER, baseline=20),
        "agent": AgentConfig(model="sonnet", budget_per_experiment="5m", max_experiments=10),
    }
    defaults.update(overrides)
    return Marker(**defaults)


class TestGateMetricImproved:
    def test_pass_when_kept(self):
        result = gate_metric_improved(Path("."), _make_marker(), FakeRunResult(kept=3))
        assert result.passed

    def test_fail_when_no_kept(self):
        result = gate_metric_improved(Path("."), _make_marker(), FakeRunResult(kept=0))
        assert not result.passed


class TestGateQualityGate:
    @patch("autoresearch.gates._run_command", return_value=(0, "quality_gate: PASS"))
    def test_pass(self, mock_cmd):
        marker = _make_marker(guard=Guard(command="echo pass"))
        result = gate_quality_gate(Path("."), marker, FakeRunResult())
        assert result.passed

    @patch("autoresearch.gates._run_command", return_value=(1, "quality_gate: FAIL"))
    def test_fail(self, mock_cmd):
        marker = _make_marker(guard=Guard(command="echo fail"))
        result = gate_quality_gate(Path("."), marker, FakeRunResult())
        assert not result.passed

    def test_skip_when_no_guard(self):
        result = gate_quality_gate(Path("."), _make_marker(), FakeRunResult())
        assert result.passed


class TestGateSecurity:
    @patch("autoresearch.gates._run_command", return_value=(0, "security_gate: PASS"))
    def test_pass(self, mock_cmd):
        marker = _make_marker(auto_merge=AutoMerge(security_command="echo pass"))
        result = gate_security(Path("."), marker, FakeRunResult())
        assert result.passed

    @patch("autoresearch.gates._run_command", return_value=(1, "1 new vulnerability"))
    def test_fail(self, mock_cmd):
        marker = _make_marker(auto_merge=AutoMerge(security_command="echo fail"))
        result = gate_security(Path("."), marker, FakeRunResult())
        assert not result.passed

    def test_skip_when_no_command(self):
        result = gate_security(Path("."), _make_marker(), FakeRunResult())
        assert result.passed


class TestGateTests:
    @patch("autoresearch.gates._run_command", return_value=(0, "5 passed"))
    def test_pass(self, mock_cmd):
        marker = _make_marker(auto_merge=AutoMerge(test_command="pytest"))
        result = gate_tests(Path("."), marker, FakeRunResult())
        assert result.passed

    @patch("autoresearch.gates._run_command", return_value=(1, "2 failed"))
    def test_fail(self, mock_cmd):
        marker = _make_marker(auto_merge=AutoMerge(test_command="pytest"))
        result = gate_tests(Path("."), marker, FakeRunResult())
        assert not result.passed


class TestGateConfidence:
    def test_pass_above_threshold(self):
        result = gate_confidence(Path("."), _make_marker(), FakeRunResult(final_confidence=1.5))
        assert result.passed

    def test_fail_below_threshold(self):
        result = gate_confidence(Path("."), _make_marker(), FakeRunResult(final_confidence=0.5))
        assert not result.passed

    def test_skip_when_none(self):
        result = gate_confidence(Path("."), _make_marker(), FakeRunResult(final_confidence=None))
        assert result.passed
        assert "--" in result.value


class TestGateChain:
    def test_all_pass(self):
        marker = _make_marker()
        rr = FakeRunResult(kept=3, final_confidence=1.5)
        result = run_gate_chain(Path("."), marker, rr, gate_names=["metric", "confidence"])
        assert result.all_passed
        assert len(result.gates) == 2

    def test_short_circuits_on_failure(self):
        marker = _make_marker()
        rr = FakeRunResult(kept=0)
        result = run_gate_chain(Path("."), marker, rr, gate_names=["metric", "confidence"])
        assert not result.all_passed
        assert len(result.gates) == 1  # stopped at metric

    def test_summary_format(self):
        chain = GateChainResult(
            all_passed=False,
            gates=[
                GateResult(name="metric", passed=True, reason="ok", value="10"),
                GateResult(name="security", passed=False, reason="1 vuln", value="FAIL"),
            ],
        )
        summary = chain.summary()
        assert "metric ✓" in summary
        assert "security ✗" in summary
