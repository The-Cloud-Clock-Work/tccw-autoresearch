"""Tests for state management."""

from pathlib import Path

from autoresearch.marker import Marker, MarkerStatus, Metric, MetricDirection, Target, LoopConfig
from autoresearch.state import (
    AppState,
    TrackedMarker,
    derive_marker_id,
    get_effective_status,
    get_tracked,
    load_state,
    save_state,
    track_marker,
    untrack_marker,
)


def _make_marker(name: str = "test-marker") -> Marker:
    return Marker(
        name=name,
        target=Target(mutable=["src/*.py"]),
        metric=Metric(
            command="pytest",
            extract="grep passed",
            direction=MetricDirection.HIGHER,
            baseline=10,
        ),
        loop=LoopConfig(),
    )


class TestLoadSaveState:
    def test_returns_empty_when_no_file(self, tmp_path):
        state = load_state(tmp_path / "state.json")
        assert state.markers == []
        assert state.daemon.running is False

    def test_roundtrip(self, tmp_path):
        path = tmp_path / "state.json"
        state = AppState()
        state.markers.append(TrackedMarker(
            id="repo:marker",
            repo_path="/tmp/repo",
            repo_name="repo",
            marker_name="marker",
            baseline=10.0,
        ))
        save_state(state, path)
        loaded = load_state(path)
        assert len(loaded.markers) == 1
        assert loaded.markers[0].id == "repo:marker"
        assert loaded.markers[0].baseline == 10.0


class TestTrackMarker:
    def test_adds_marker(self, tmp_path):
        state = AppState()
        marker = _make_marker()
        repo_path = tmp_path / "myrepo"
        repo_path.mkdir()
        tracked = track_marker(state, repo_path, marker)
        assert tracked.id == "myrepo:test-marker"
        assert tracked.marker_name == "test-marker"
        assert tracked.baseline == 10
        assert len(state.markers) == 1

    def test_does_not_duplicate(self, tmp_path):
        state = AppState()
        marker = _make_marker()
        repo_path = tmp_path / "myrepo"
        repo_path.mkdir()
        track_marker(state, repo_path, marker)
        track_marker(state, repo_path, marker)
        assert len(state.markers) == 1


class TestUntrackMarker:
    def test_removes_existing(self, tmp_path):
        state = AppState()
        marker = _make_marker()
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        track_marker(state, repo_path, marker)
        assert untrack_marker(state, "repo:test-marker") is True
        assert len(state.markers) == 0

    def test_returns_false_for_missing(self):
        state = AppState()
        assert untrack_marker(state, "nope:nope") is False


class TestGetTracked:
    def test_finds_by_id(self, tmp_path):
        state = AppState()
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        track_marker(state, repo_path, _make_marker())
        found = get_tracked(state, "repo:test-marker")
        assert found is not None
        assert found.marker_name == "test-marker"

    def test_returns_none_for_missing(self):
        state = AppState()
        assert get_tracked(state, "nope:nope") is None


class TestEffectiveStatus:
    def test_override_wins(self):
        tracked = TrackedMarker(
            id="r:m", repo_path="/tmp", repo_name="r", marker_name="m",
            status_override=MarkerStatus.SKIP,
        )
        assert get_effective_status(tracked, MarkerStatus.ACTIVE) == MarkerStatus.SKIP

    def test_yaml_when_no_override(self):
        tracked = TrackedMarker(
            id="r:m", repo_path="/tmp", repo_name="r", marker_name="m",
        )
        assert get_effective_status(tracked, MarkerStatus.PAUSED) == MarkerStatus.PAUSED


class TestDeriveMarkerId:
    def test_uses_dirname(self):
        assert derive_marker_id(Path("/home/user/dev/antoncore"), "auth") == "antoncore:auth"

    def test_conflict_uses_full_path(self, tmp_path):
        repo_a = tmp_path / "workspace1" / "myrepo"
        repo_b = tmp_path / "workspace2" / "myrepo"
        repo_a.mkdir(parents=True)
        repo_b.mkdir(parents=True)
        state = AppState()
        track_marker(state, repo_a, _make_marker("marker-a"))
        # repo_b has same dirname "myrepo" but different path — should use full path
        marker_id = derive_marker_id(repo_b, "marker-b", state)
        assert str(repo_b.resolve()) in marker_id
