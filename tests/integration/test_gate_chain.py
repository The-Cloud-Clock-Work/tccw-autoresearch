"""Integration Test 4: Gate chain with real shell commands."""

from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock

from autoresearch.gates import run_gate_chain, gate_security, gate_tests


@dataclass
class FakeRunResult:
    marker_name: str = "test"
    experiments: int = 1
    kept: int = 1
    discarded: int = 0
    crashed: int = 0
    final_metric: float = 3.0
    final_confidence: float = 1.0
    final_status: str = "completed"
    branch: str = "autoresearch/test"
    worktree_path: str = "/tmp/wt"


def _make_marker(security_command=None, test_command=None, gates=None):
    marker = MagicMock()
    marker.guard.command = None
    marker.auto_merge.security_command = security_command
    marker.auto_merge.test_command = test_command
    marker.auto_merge.gates = gates or ["security", "tests"]
    marker.auto_merge.min_confidence = 0.5
    return marker


class TestGateChainReal:
    def test_passing_gates(self, git_repo):
        marker = _make_marker(
            security_command="echo 'no secrets found'",
            test_command="python3 -c 'import sys; sys.exit(0)'",
        )
        result = run_gate_chain(git_repo, marker, FakeRunResult())
        assert result.all_passed is True
        assert len(result.gates) == 2

    def test_failing_test_gate(self, git_repo):
        marker = _make_marker(
            security_command="echo 'clean'",
            test_command="python3 -c 'import sys; sys.exit(1)'",
        )
        result = run_gate_chain(git_repo, marker, FakeRunResult())
        assert result.all_passed is False
        failed = [g for g in result.gates if not g.passed]
        assert any(g.name == "tests" for g in failed)

    def test_failing_security_gate(self, git_repo):
        marker = _make_marker(
            security_command="false",
            test_command="true",
        )
        result = run_gate_chain(git_repo, marker, FakeRunResult())
        assert result.all_passed is False
        assert result.gates[0].name == "security"
        assert result.gates[0].passed is False

    def test_no_commands_configured_passes(self, git_repo):
        marker = _make_marker()
        result = run_gate_chain(git_repo, marker, FakeRunResult())
        assert result.all_passed is True

    def test_metric_gate_with_zero_kept_fails(self, git_repo):
        marker = _make_marker()
        run_result = FakeRunResult(kept=0)
        result = run_gate_chain(git_repo, marker, run_result, gate_names=["metric"])
        assert result.all_passed is False

    def test_real_ruff_as_security_gate(self, git_repo):
        marker = _make_marker(security_command="ruff check . 2>&1; true")
        result = run_gate_chain(git_repo, marker, FakeRunResult(), gate_names=["security"])
        assert result.all_passed is True
