"""Tests for marker schema and .autoresearch.yaml parsing."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from autoresearch.marker import (
    Guard,
    Escalation,
    Marker,
    MarkerFile,
    MarkerStatus,
    MetricDirection,
    Schedule,
    ResultsConfig,
    find_marker_file,
    get_marker,
    load_markers,
    resolve_marker_id,
)

FIXTURES = Path(__file__).parent / "fixtures"


class TestLoadMarkers:
    def test_valid_marker_loads_two_markers(self):
        mf = load_markers(FIXTURES / "valid_marker.yaml")
        assert len(mf.markers) == 2

    def test_valid_marker_first_has_correct_fields(self):
        mf = load_markers(FIXTURES / "valid_marker.yaml")
        m = mf.markers[0]
        assert m.name == "auth-flow-reliability"
        assert m.status == MarkerStatus.ACTIVE
        assert m.metric.direction == MetricDirection.HIGHER
        assert m.metric.baseline == 24
        assert m.metric.target == 34
        assert m.guard.command is not None
        assert m.guard.threshold == 50
        assert m.escalation.refine_after == 3
        assert m.agent.model == "sonnet"
        assert m.agent.max_experiments == 50

    def test_valid_marker_second_is_skip(self):
        mf = load_markers(FIXTURES / "valid_marker.yaml")
        m = mf.markers[1]
        assert m.name == "build-speed"
        assert m.status == MarkerStatus.SKIP
        assert m.metric.direction == MetricDirection.LOWER

    def test_minimal_marker_fills_defaults(self):
        mf = load_markers(FIXTURES / "minimal_marker.yaml")
        assert len(mf.markers) == 1
        m = mf.markers[0]
        assert m.name == "simple-test"
        assert m.status == MarkerStatus.ACTIVE  # default
        assert m.guard == Guard()
        assert m.escalation == Escalation()
        assert m.schedule == Schedule()
        assert m.results == ResultsConfig()

    def test_invalid_marker_raises(self):
        with pytest.raises(ValidationError):
            load_markers(FIXTURES / "invalid_marker.yaml")


class TestFindMarkerFile:
    def test_finds_in_fixtures_dir(self, tmp_path):
        marker = tmp_path / ".autoresearch.yaml"
        marker.write_text("markers: []")
        assert find_marker_file(tmp_path) == marker

    def test_returns_none_when_missing(self, tmp_path):
        assert find_marker_file(tmp_path) is None


class TestGetMarker:
    def test_finds_by_name(self):
        mf = load_markers(FIXTURES / "valid_marker.yaml")
        m = get_marker(mf, "auth-flow-reliability")
        assert m is not None
        assert m.name == "auth-flow-reliability"

    def test_returns_none_for_wrong_name(self):
        mf = load_markers(FIXTURES / "valid_marker.yaml")
        assert get_marker(mf, "nonexistent") is None


class TestResolveMarkerId:
    def test_splits_correctly(self):
        repo, name = resolve_marker_id("antoncore:auth-flow")
        assert repo == "antoncore"
        assert name == "auth-flow"

    def test_handles_colon_in_name(self):
        repo, name = resolve_marker_id("repo:name:with:colons")
        assert repo == "repo"
        assert name == "name:with:colons"

    def test_raises_on_invalid(self):
        with pytest.raises(ValueError):
            resolve_marker_id("no-colon-here")


class TestMarkerDefaults:
    def test_marker_status_default_active(self):
        from autoresearch.marker import Metric, MetricDirection, Target
        m = Marker(
            name="test",
            target=Target(mutable=["src/foo.py"]),
            metric=Metric(command="pytest", extract="grep", direction=MetricDirection.HIGHER, baseline=0),
        )
        assert m.status == MarkerStatus.ACTIVE
        assert m.description == ""

    def test_guard_defaults(self):
        from autoresearch.marker import Guard
        g = Guard()
        assert g.command is None
        assert g.threshold is None
        assert g.rework_attempts == 2

    def test_escalation_defaults(self):
        from autoresearch.marker import Escalation
        e = Escalation()
        assert e.refine_after == 3
        assert e.pivot_after == 5
        assert e.search_after_pivots == 2
        assert e.halt_after_pivots == 3

    def test_agent_config_defaults(self):
        from autoresearch.marker import AgentConfig
        ac = AgentConfig()
        assert ac.model == "sonnet"
        assert ac.max_experiments == 50
        assert ac.budget_per_experiment == "10m"
        assert ac.effort == "medium"
        assert ac.permission_mode == "bypassPermissions"

    def test_marker_status_enum_values(self):
        assert MarkerStatus.ACTIVE == "active"
        assert MarkerStatus.SKIP == "skip"
        assert MarkerStatus.PAUSED == "paused"
        assert MarkerStatus.COMPLETED == "completed"

    def test_find_marker_file_prefers_config_dir(self, tmp_path):
        from autoresearch.marker import find_marker_file, CONFIG_DIR, CONFIG_FILENAME, MARKER_FILENAME
        # Create both paths
        config_dir = tmp_path / CONFIG_DIR
        config_dir.mkdir()
        config_file = config_dir / CONFIG_FILENAME
        config_file.write_text("markers: []")
        legacy = tmp_path / MARKER_FILENAME
        legacy.write_text("markers: []")
        # Should prefer config dir
        result = find_marker_file(tmp_path)
        assert result == config_file

    def test_marker_file_get_marker_returns_none_for_missing(self):
        mf = MarkerFile(markers=[])
        assert get_marker(mf, "nonexistent") is None
