"""Tests for metrics.py — harness execution and confidence scoring."""

from pathlib import Path
from unittest.mock import patch

import pytest

from autoresearch.metrics import (
    HarnessResult,
    GuardResult,
    compute_confidence,
    confidence_label,
    is_improved,
    run_guard,
    run_harness,
)


@pytest.fixture
def work_dir(tmp_path):
    """Temp directory simulating a worktree."""
    return tmp_path


class TestRunHarness:
    def test_successful_extraction(self, work_dir):
        result = run_harness(
            command='echo "Tests: 24 passed"',
            extract=r"grep -oP '\d+(?= passed)'",
            worktree_path=work_dir,
            marker_name="test-marker",
        )
        assert result.metric == 24.0
        assert result.exit_code == 0
        assert result.log_path.exists()

    def test_crash_returns_none_metric(self, work_dir):
        result = run_harness(
            command='echo "no numbers here"',
            extract=r"grep -oP '\d+(?= passed)'",
            worktree_path=work_dir,
            marker_name="test-marker",
        )
        assert result.metric is None

    def test_timeout_returns_none_metric(self, work_dir):
        result = run_harness(
            command="sleep 10",
            extract="cat",
            worktree_path=work_dir,
            marker_name="test-marker",
            timeout_seconds=1,
        )
        assert result.metric is None
        assert result.exit_code == -1

    def test_writes_run_log(self, work_dir):
        run_harness(
            command='echo "output line"',
            extract="cat",
            worktree_path=work_dir,
            marker_name="test-marker",
        )
        log = work_dir / ".autoresearch" / "test-marker" / "run.log"
        assert log.exists()
        assert "output line" in log.read_text()

    def test_extracts_last_number(self, work_dir):
        result = run_harness(
            command='echo "scores: 10 20 30"',
            extract="cat",
            worktree_path=work_dir,
            marker_name="test-marker",
        )
        assert result.metric == 30.0

    def test_float_extraction(self, work_dir):
        result = run_harness(
            command='echo "coverage: 87.5%"',
            extract=r"grep -oP '\d+\.\d+'",
            worktree_path=work_dir,
            marker_name="test-marker",
        )
        assert result.metric == 87.5


class TestRunGuard:
    def test_exit_code_pass(self, work_dir):
        result = run_guard(
            command="true",
            extract=None,
            threshold=None,
            worktree_path=work_dir,
        )
        assert result.passed is True

    def test_exit_code_fail(self, work_dir):
        result = run_guard(
            command="false",
            extract=None,
            threshold=None,
            worktree_path=work_dir,
        )
        assert result.passed is False

    def test_threshold_pass(self, work_dir):
        result = run_guard(
            command='echo "30 passed"',
            extract=r"grep -oP '\d+(?= passed)'",
            threshold=25.0,
            worktree_path=work_dir,
        )
        assert result.passed is True
        assert result.value == 30.0

    def test_threshold_fail(self, work_dir):
        result = run_guard(
            command='echo "20 passed"',
            extract=r"grep -oP '\d+(?= passed)'",
            threshold=25.0,
            worktree_path=work_dir,
        )
        assert result.passed is False
        assert result.value == 20.0

    def test_timeout_fails(self, work_dir):
        result = run_guard(
            command="sleep 10",
            extract=None,
            threshold=None,
            worktree_path=work_dir,
            timeout_seconds=1,
        )
        assert result.passed is False


class TestIsImproved:
    def test_higher_improved(self):
        assert is_improved(31, 24, "higher") is True

    def test_higher_not_improved(self):
        assert is_improved(20, 24, "higher") is False

    def test_higher_equal_not_improved(self):
        assert is_improved(24, 24, "higher") is False

    def test_lower_improved(self):
        assert is_improved(100, 200, "lower") is True

    def test_lower_not_improved(self):
        assert is_improved(200, 100, "lower") is False

    def test_lower_equal_not_improved(self):
        assert is_improved(100, 100, "lower") is False


class TestComputeConfidence:
    def test_too_few_samples(self):
        assert compute_confidence([24, 27], 24, 27) is None

    def test_known_values(self):
        kept = [24.0, 27.0, 31.0]
        med = 27.0  # median
        devs = [3.0, 0.0, 4.0]  # |x - med|
        mad = 3.0  # median of devs
        expected = abs(31.0 - 24.0) / (3.0 * 1.4826)  # ~1.574

        result = compute_confidence(kept, 24.0, 31.0)
        assert result is not None
        assert abs(result - expected) < 0.01

    def test_zero_mad_different_values(self):
        result = compute_confidence([10.0, 10.0, 10.0], 5.0, 10.0)
        assert result == float("inf")

    def test_zero_mad_same_as_baseline(self):
        result = compute_confidence([10.0, 10.0, 10.0], 10.0, 10.0)
        assert result is None


class TestConfidenceLabel:
    def test_none(self):
        assert confidence_label(None) == "--"

    def test_high(self):
        assert confidence_label(2.5) == "HIGH"

    def test_medium(self):
        assert confidence_label(1.5) == "MEDIUM"

    def test_low(self):
        assert confidence_label(0.5) == "LOW"

    def test_boundary_high(self):
        assert confidence_label(2.0) == "HIGH"

    def test_boundary_medium(self):
        assert confidence_label(1.0) == "MEDIUM"


class TestExtractMetricEdgeCases:
    def test_negative_decimal_without_leading_zero(self, work_dir):
        """Regex should match -.5 as a valid number."""
        result = run_harness(
            command='echo "value: -.5"',
            extract="cat",
            worktree_path=work_dir,
            marker_name="test-marker",
        )
        assert result.metric == -0.5

    def test_negative_integer(self, work_dir):
        result = run_harness(
            command='echo "delta: -3"',
            extract="cat",
            worktree_path=work_dir,
            marker_name="test-marker",
        )
        assert result.metric == -3.0

    def test_decimal_without_leading_zero(self, work_dir):
        result = run_harness(
            command='echo "rate: .75"',
            extract="cat",
            worktree_path=work_dir,
            marker_name="test-marker",
        )
        assert result.metric == 0.75
