"""Tests for results management."""


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

    def test_get_latest_metric_only_discards(self):
        results = [
            ExperimentResult(commit="a", metric=5.0, status="discard", description=""),
            ExperimentResult(commit="b", metric=6.0, status="crash", description=""),
        ]
        assert get_latest_metric(results) is None

    def test_get_latest_metric_last_is_keep(self):
        results = [
            ExperimentResult(commit="a", metric=5.0, status="keep", description=""),
            ExperimentResult(commit="b", metric=10.0, status="keep", description=""),
        ]
        assert get_latest_metric(results) == 10.0

    def test_get_kept_metrics_all_discards(self):
        results = [
            ExperimentResult(commit="x", metric=99.0, status="discard", description=""),
        ]
        assert get_kept_metrics(results) == []


class TestExperimentResultDefaults:
    def test_guard_defaults_to_dashes(self):
        r = ExperimentResult(commit="abc", metric=1.0, status="keep", description="")
        assert r.guard == "--"

    def test_confidence_defaults_to_dashes(self):
        r = ExperimentResult(commit="abc", metric=1.0, status="keep", description="")
        assert r.confidence == "--"

    def test_metric_float_precision(self, tmp_path):
        r = ExperimentResult(commit="abc1234", metric=87.654321, status="keep", description="precision")
        append_result(tmp_path, "test", r)
        results = read_results(tmp_path, "test")
        assert abs(results[0].metric - 87.654321) < 0.0001

    def test_multiple_appends_three_entries(self, tmp_path):
        for i in range(3):
            r = ExperimentResult(commit=f"commit{i}", metric=float(i * 10), status="keep", description=f"exp {i}")
            append_result(tmp_path, "multi", r)
        results = read_results(tmp_path, "multi")
        assert len(results) == 3
        assert results[2].commit == "commit2"

    def test_discard_status_preserved(self, tmp_path):
        r = ExperimentResult(commit="dd1", metric=5.0, status="discard", description="nope")
        append_result(tmp_path, "test", r)
        results = read_results(tmp_path, "test")
        assert results[0].status == "discard"

    def test_crash_status_preserved(self, tmp_path):
        r = ExperimentResult(commit="cc1", metric=0.0, status="crash", description="boom")
        append_result(tmp_path, "test", r)
        results = read_results(tmp_path, "test")
        assert results[0].status == "crash"


# ---------------------------------------------------------------------------
# Extended results tests
# ---------------------------------------------------------------------------

class TestGetLatestMetricExtended:
    def test_empty_list_returns_none(self):
        from autoresearch.results import get_latest_metric
        assert get_latest_metric([]) is None

    def test_only_discard_returns_none(self):
        from autoresearch.results import get_latest_metric, ExperimentResult
        results = [ExperimentResult(commit="a", metric=5.0, status="discard", description="")]
        assert get_latest_metric(results) is None

    def test_returns_last_keep(self):
        from autoresearch.results import get_latest_metric, ExperimentResult
        results = [
            ExperimentResult(commit="a", metric=10.0, status="keep", description=""),
            ExperimentResult(commit="b", metric=20.0, status="keep", description=""),
        ]
        assert get_latest_metric(results) == 20.0

    def test_skips_crash_finds_keep(self):
        from autoresearch.results import get_latest_metric, ExperimentResult
        results = [
            ExperimentResult(commit="a", metric=10.0, status="keep", description=""),
            ExperimentResult(commit="b", metric=0.0, status="crash", description=""),
        ]
        assert get_latest_metric(results) == 10.0

    def test_last_keep_among_mixed(self):
        from autoresearch.results import get_latest_metric, ExperimentResult
        results = [
            ExperimentResult(commit="a", metric=5.0, status="keep", description=""),
            ExperimentResult(commit="b", metric=3.0, status="discard", description=""),
            ExperimentResult(commit="c", metric=8.0, status="keep", description=""),
            ExperimentResult(commit="d", metric=2.0, status="crash", description=""),
        ]
        assert get_latest_metric(results) == 8.0


class TestGetKeptMetricsExtended:
    def test_empty_returns_empty(self):
        from autoresearch.results import get_kept_metrics
        assert get_kept_metrics([]) == []

    def test_only_discard_returns_empty(self):
        from autoresearch.results import get_kept_metrics, ExperimentResult
        results = [ExperimentResult(commit="a", metric=1.0, status="discard", description="")]
        assert get_kept_metrics(results) == []

    def test_all_keep_returns_all(self):
        from autoresearch.results import get_kept_metrics, ExperimentResult
        results = [
            ExperimentResult(commit="a", metric=1.0, status="keep", description=""),
            ExperimentResult(commit="b", metric=2.0, status="keep", description=""),
            ExperimentResult(commit="c", metric=3.0, status="keep", description=""),
        ]
        assert get_kept_metrics(results) == [1.0, 2.0, 3.0]

    def test_mixed_returns_only_kept(self):
        from autoresearch.results import get_kept_metrics, ExperimentResult
        results = [
            ExperimentResult(commit="a", metric=10.0, status="keep", description=""),
            ExperimentResult(commit="b", metric=20.0, status="discard", description=""),
            ExperimentResult(commit="c", metric=30.0, status="crash", description=""),
            ExperimentResult(commit="d", metric=40.0, status="keep", description=""),
        ]
        assert get_kept_metrics(results) == [10.0, 40.0]


class TestAppendAndReadExtended:
    def test_confidence_stored_and_retrieved(self, tmp_path):
        from autoresearch.results import ExperimentResult, append_result, read_results
        r = ExperimentResult(commit="abc", metric=1.0, status="keep", description="", confidence="HIGH")
        append_result(tmp_path, "test", r)
        results = read_results(tmp_path, "test")
        assert results[0].confidence == "HIGH"

    def test_guard_stored_and_retrieved(self, tmp_path):
        from autoresearch.results import ExperimentResult, append_result, read_results
        r = ExperimentResult(commit="abc", metric=1.0, status="keep", description="", guard="PASS")
        append_result(tmp_path, "test", r)
        results = read_results(tmp_path, "test")
        assert results[0].guard == "PASS"

    def test_description_with_spaces(self, tmp_path):
        from autoresearch.results import ExperimentResult, append_result, read_results
        r = ExperimentResult(commit="abc", metric=1.0, status="keep", description="added more tests")
        append_result(tmp_path, "test", r)
        results = read_results(tmp_path, "test")
        assert results[0].description == "added more tests"

    def test_zero_metric(self, tmp_path):
        from autoresearch.results import ExperimentResult, append_result, read_results
        r = ExperimentResult(commit="abc", metric=0.0, status="crash", description="fail")
        append_result(tmp_path, "test", r)
        results = read_results(tmp_path, "test")
        assert results[0].metric == 0.0

    def test_negative_metric(self, tmp_path):
        from autoresearch.results import ExperimentResult, append_result, read_results
        r = ExperimentResult(commit="abc", metric=-5.0, status="keep", description="neg")
        append_result(tmp_path, "test", r)
        results = read_results(tmp_path, "test")
        assert results[0].metric == -5.0

    def test_many_results_order_preserved(self, tmp_path):
        from autoresearch.results import ExperimentResult, append_result, read_results
        metrics = [1.0, 2.0, 3.0, 4.0, 5.0]
        for i, m in enumerate(metrics):
            r = ExperimentResult(commit=f"c{i}", metric=m, status="keep", description="")
            append_result(tmp_path, "ordered", r)
        results = read_results(tmp_path, "ordered")
        assert [r.metric for r in results] == metrics
