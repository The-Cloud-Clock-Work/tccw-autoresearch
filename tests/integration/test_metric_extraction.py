"""Integration Test 2: Real metric command execution + number extraction."""

import re
import subprocess

from autoresearch.marker import load_markers
from autoresearch.metrics import run_harness


class TestMetricExtraction:
    def test_ruff_metric_detects_errors(self, git_repo_with_ruff_errors, write_marker_config):
        write_marker_config(git_repo_with_ruff_errors)
        markers = load_markers(git_repo_with_ruff_errors / ".autoresearch" / "config.yaml")
        m = markers.markers[0]

        result = run_harness(m.metric.command, m.metric.extract, git_repo_with_ruff_errors, m.name)
        assert result.metric is not None
        assert isinstance(result.metric, (int, float))
        assert result.metric > 0

    def test_ruff_metric_matches_actual_output(self, git_repo_with_ruff_errors, write_marker_config):
        write_marker_config(git_repo_with_ruff_errors)

        ruff_out = subprocess.run(
            ["ruff", "check", "."],
            cwd=git_repo_with_ruff_errors,
            capture_output=True, text=True,
        )
        match = re.search(r"Found (\d+)", ruff_out.stdout + ruff_out.stderr)
        expected = int(match.group(1)) if match else None

        markers = load_markers(git_repo_with_ruff_errors / ".autoresearch" / "config.yaml")
        m = markers.markers[0]
        result = run_harness(m.metric.command, m.metric.extract, git_repo_with_ruff_errors, m.name)
        assert result.metric == expected

    def test_echo_metric_extraction(self, git_repo, write_marker_config):
        write_marker_config(
            git_repo,
            command="echo 'Found 42 issues'",
            extract="grep -oP '\\d+'",
        )
        markers = load_markers(git_repo / ".autoresearch" / "config.yaml")
        m = markers.markers[0]
        result = run_harness(m.metric.command, m.metric.extract, git_repo, m.name)
        assert result.metric == 42

    def test_failing_metric_command(self, git_repo, write_marker_config):
        write_marker_config(
            git_repo,
            command="false",
            extract="cat",
        )
        markers = load_markers(git_repo / ".autoresearch" / "config.yaml")
        m = markers.markers[0]
        result = run_harness(m.metric.command, m.metric.extract, git_repo, m.name)
        assert result.metric is None
