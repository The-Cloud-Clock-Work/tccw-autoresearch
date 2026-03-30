"""Tests for results management."""

from pathlib import Path

from autoresearch.results import (
    ExperimentResult,
    append_result,
    ensure_results_dir,
    get_kept_metrics,
    get_latest_metric,
    read_results,
)


class TestEnsureResultsDir:
    def test_creates_dir(self, tmp_path):
        path = ensure_results_dir(tmp_path, "my-marker")
        assert path.is_dir()
        assert path == tmp_path / ".autoresearch" / "my-marker"

    def test_idempotent(self, tmp_path):
        ensure_results_dir(tmp_path, "my-marker")
        ensure_results_dir(tmp_path, "my-marker")
        assert (tmp_path / ".autoresearch" / "my-marker").is_dir()


class TestAppendAndReadResults:
    def test_creates_file_with_header(self, tmp_path):
        r = ExperimentResult(
            commit="a1b2c3d", metric=24.0, status="keep", description="baseline"
        )
        append_result(tmp_path, "test", r)
        tsv = (tmp_path / ".autoresearch" / "test" / "results.tsv").read_text()
        lines = tsv.strip().split("\n")
        assert lines[0].startswith("commit")
        assert "a1b2c3d" in lines[1]

    def test_appends_to_existing(self, tmp_path):
        r1 = ExperimentResult(commit="aaa", metric=10.0, status="keep", description="first")
        r2 = ExperimentResult(commit="bbb", metric=15.0, status="keep", description="second")
        append_result(tmp_path, "test", r1)
        append_result(tmp_path, "test", r2)
        results = read_results(tmp_path, "test")
        assert len(results) == 2
        assert results[0].commit == "aaa"
        assert results[1].commit == "bbb"

    def test_read_empty_returns_empty(self, tmp_path):
        assert read_results(tmp_path, "nonexistent") == []

    def test_preserves_all_fields(self, tmp_path):
        r = ExperimentResult(
            commit="abc1234",
            metric=31.0,
            guard="pass",
            status="keep",
            confidence="2.1",
            description="add connection pooling",
        )
        append_result(tmp_path, "test", r)
        results = read_results(tmp_path, "test")
        assert len(results) == 1
        loaded = results[0]
        assert loaded.commit == "abc1234"
        assert loaded.metric == 31.0
        assert loaded.guard == "pass"
        assert loaded.status == "keep"
        assert loaded.confidence == "2.1"
        assert loaded.description == "add connection pooling"


class TestMetricHelpers:
    def _make_results(self) -> list[ExperimentResult]:
        return [
            ExperimentResult(commit="a", metric=10, status="keep", description=""),
            ExperimentResult(commit="b", metric=8, status="discard", description=""),
            ExperimentResult(commit="c", metric=0, status="crash", description=""),
            ExperimentResult(commit="d", metric=15, status="keep", description=""),
            ExperimentResult(commit="e", metric=12, status="discard", description=""),
        ]

    def test_get_latest_metric(self):
        results = self._make_results()
        assert get_latest_metric(results) == 15.0

    def test_get_latest_metric_empty(self):
        assert get_latest_metric([]) is None

    def test_get_kept_metrics(self):
        results = self._make_results()
        assert get_kept_metrics(results) == [10.0, 15.0]

    def test_get_kept_metrics_empty(self):
        assert get_kept_metrics([]) == []
