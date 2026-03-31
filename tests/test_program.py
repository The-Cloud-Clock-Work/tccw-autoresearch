"""Tests for program.py — program.md template generation."""

from autoresearch.marker import (
    Escalation,
    LoopConfig,
    Marker,
    MarkerStatus,
    Metric,
    MetricDirection,
    ResultsConfig,
    Schedule,
    Target,
)
from autoresearch.program import (
    _escalation_instructions,
    _format_file_list,
    _format_ideas_section,
    _format_results_section,
    generate_program,
)


def _make_marker(**overrides) -> Marker:
    """Create a test marker with sensible defaults."""
    defaults = {
        "name": "test-marker",
        "description": "Test marker",
        "status": MarkerStatus.ACTIVE,
        "target": Target(
            mutable=["src/auth.py", "src/utils.py"],
            immutable=["tests/test_auth.py"],
        ),
        "metric": Metric(
            command="pytest tests/test_auth.py -q",
            extract=r"grep -oP '\d+(?= passed)'",
            direction=MetricDirection.HIGHER,
            baseline=24,
        ),
        "loop": LoopConfig(),
        "escalation": Escalation(),
        "schedule": Schedule(),
        "results": ResultsConfig(),
    }
    defaults.update(overrides)
    return Marker(**defaults)


class TestGenerateProgram:
    def test_contains_mutable_files(self):
        marker = _make_marker()
        result = generate_program(marker, None, "", "", "normal")
        assert "src/auth.py" in result
        assert "src/utils.py" in result

    def test_contains_immutable_files(self):
        marker = _make_marker()
        result = generate_program(marker, None, "", "", "normal")
        assert "tests/test_auth.py" in result

    def test_contains_metric_info(self):
        marker = _make_marker()
        result = generate_program(marker, None, "", "", "normal")
        assert "pytest tests/test_auth.py -q" in result
        assert "higher is better" in result
        assert "24" in result

    def test_no_experiments_yet(self):
        marker = _make_marker()
        result = generate_program(marker, None, "", "", "normal")
        assert "no experiments yet" in result

    def test_current_best_shown(self):
        marker = _make_marker()
        result = generate_program(marker, 31.0, "", "", "normal")
        assert "Current best: 31.0" in result
        assert "Baseline: 24" in result

    def test_target_shown_when_set(self):
        marker = _make_marker(
            metric=Metric(
                command="pytest -q",
                extract="cat",
                direction=MetricDirection.HIGHER,
                baseline=24,
                target=34,
            )
        )
        result = generate_program(marker, None, "", "", "normal")
        assert "Target: 34" in result

    def test_target_absent_when_none(self):
        marker = _make_marker()
        result = generate_program(marker, None, "", "", "normal")
        assert "Target:" not in result

    def test_budget_shown(self):
        marker = _make_marker(loop=LoopConfig(budget_per_experiment="5m"))
        result = generate_program(marker, None, "", "", "normal")
        assert "5m" in result

    def test_no_escalation_for_normal(self):
        marker = _make_marker()
        result = generate_program(marker, None, "", "", "normal")
        assert "REFINE" not in result
        assert "PIVOT" not in result
        assert "SEARCH" not in result

    def test_refine_escalation(self):
        marker = _make_marker()
        result = generate_program(marker, None, "", "", "refine")
        assert "REFINE Directive" in result

    def test_pivot_escalation(self):
        marker = _make_marker()
        result = generate_program(marker, None, "", "", "pivot")
        assert "PIVOT Directive" in result

    def test_search_escalation(self):
        marker = _make_marker()
        result = generate_program(marker, None, "", "", "search")
        assert "SEARCH Directive" in result

    def test_results_summary_included(self):
        summary = "a1b2c3d\t24\tpass\tkeep\t--\tbaseline"
        marker = _make_marker()
        result = generate_program(marker, 24.0, summary, "", "normal")
        assert "a1b2c3d" in result
        assert "Results History" in result

    def test_results_truncated_over_20(self):
        lines = [f"hash{i}\t{i}\tpass\tkeep\t--\texperiment {i}" for i in range(30)]
        summary = "\n".join(lines)
        marker = _make_marker()
        result = generate_program(marker, 29.0, summary, "", "normal")
        assert "showing last 20" in result
        assert "hash10" in result
        assert "hash0" not in result

    def test_ideas_included(self):
        ideas = "## Discarded but Promising\n- Try connection pooling"
        marker = _make_marker()
        result = generate_program(marker, None, "", ideas, "normal")
        assert "connection pooling" in result
        assert "Ideas Backlog" in result

    def test_empty_ideas_omitted(self):
        marker = _make_marker()
        result = generate_program(marker, None, "", "", "normal")
        assert "Ideas Backlog" not in result


class TestEscalationInstructions:
    def test_normal_empty(self):
        assert _escalation_instructions("normal") == ""

    def test_refine(self):
        text = _escalation_instructions("refine")
        assert "REFINE" in text
        assert "Adjust your strategy" in text

    def test_pivot(self):
        text = _escalation_instructions("pivot")
        assert "PIVOT" in text
        assert "Abandon" in text

    def test_search(self):
        text = _escalation_instructions("search")
        assert "SEARCH" in text
        assert "research external" in text

    def test_unknown_level_empty(self):
        assert _escalation_instructions("unknown") == ""


class TestFormatHelpers:
    def test_file_list(self):
        result = _format_file_list(["a.py", "b.py"])
        assert "- a.py" in result
        assert "- b.py" in result

    def test_empty_file_list(self):
        result = _format_file_list([])
        assert "(none)" in result

    def test_results_section_empty(self):
        assert _format_results_section("") == ""

    def test_ideas_section_empty(self):
        assert _format_ideas_section("") == ""
        assert _format_ideas_section("   \n  ") == ""

    def test_results_section_exactly_20_not_truncated(self):
        lines = "\n".join(f"line{i}" for i in range(20))
        result = _format_results_section(lines)
        assert "last 20" not in result
        for i in range(20):
            assert f"line{i}" in result

    def test_results_section_over_20_truncated(self):
        lines = "\n".join(f"line{i}" for i in range(21))
        result = _format_results_section(lines)
        assert "last 20" in result
        assert "line0" not in result  # first entry dropped
        assert "line20" in result  # last entry kept

    def test_ideas_section_with_content(self):
        result = _format_ideas_section("## Near-Misses\n- something\n")
        assert "Ideas Backlog" in result
        assert "Near-Misses" in result

    def test_generate_no_mutable_files(self):
        from autoresearch.marker import Target, Metric, MetricDirection
        marker = _make_marker(target=Target(mutable=[], immutable=[]))
        result = generate_program(marker, None, "", "")
        assert "(none)" in result

    def test_generate_with_ideas(self):
        result = generate_program(_make_marker(), 30.0, "summary", "## Near-Misses\n- idea\n")
        assert "Ideas Backlog" in result
        assert "- idea" in result

    def test_generate_lower_direction(self):
        from autoresearch.marker import Metric, MetricDirection
        marker = _make_marker(
            metric=_make_marker().metric.model_copy(update={"direction": MetricDirection.LOWER})
        )
        result = generate_program(marker, 5.0, "", "")
        assert "lower" in result
