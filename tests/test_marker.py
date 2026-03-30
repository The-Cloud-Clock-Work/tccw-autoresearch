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
        assert m.loop.model == "sonnet"
        assert m.loop.max_experiments == 50

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
