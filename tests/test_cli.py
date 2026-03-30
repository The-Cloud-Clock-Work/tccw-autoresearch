"""Tests for CLI commands."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from autoresearch.cli import app
from autoresearch.marker import Marker, MarkerFile, MarkerStatus, Metric, Target, LoopConfig
from autoresearch.state import AppState, TrackedMarker, save_state

runner = CliRunner()


def _make_marker(name: str = "test-marker", status: MarkerStatus = MarkerStatus.ACTIVE) -> Marker:
    return Marker(
        name=name,
        description="test",
        status=status,
        target=Target(mutable=["src/main.py"]),
        metric=Metric(command="echo 42", extract=r"\d+", direction="higher", baseline=10.0, target=50.0),
        loop=LoopConfig(model="sonnet", budget_per_experiment="5m", max_experiments=10),
    )


def _make_tracked(
    repo_path: str = "/tmp/fakerepo",
    marker_name: str = "test-marker",
    marker_id: str = "fakerepo:test-marker",
    **kwargs,
) -> TrackedMarker:
    return TrackedMarker(
        id=marker_id,
        repo_path=repo_path,
        repo_name="fakerepo",
        marker_name=marker_name,
        **kwargs,
    )


def _save_state_file(state: AppState, path: Path) -> None:
    save_state(state, state_path=path)


# ---------------------------------------------------------------------------
# Headless list
# ---------------------------------------------------------------------------

class TestHeadlessList:
    def test_empty_state(self, tmp_path):
        state_path = tmp_path / "state.json"
        _save_state_file(AppState(), state_path)
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "list"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["status"] == "ok"
        assert data["data"] == []

    def test_with_tracked_markers(self, tmp_path):
        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        marker = _make_marker()
        mf = MarkerFile(markers=[marker])

        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.find_marker_file", return_value=Path("/tmp/fakerepo/.autoresearch.yaml")),
            patch("autoresearch.cli.load_markers", return_value=mf),
        ):
            result = runner.invoke(app, ["--headless", "list"])

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["status"] == "ok"
        assert len(data["data"]) == 1
        assert data["data"][0]["id"] == "fakerepo:test-marker"
        assert data["data"][0]["status"] == "active"

    def test_with_missing_repo(self, tmp_path):
        tracked = _make_tracked()
        state = AppState(markers=[tracked])

        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.find_marker_file", return_value=None),
        ):
            result = runner.invoke(app, ["--headless", "list"])

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["data"][0]["status"] == "unknown"


# ---------------------------------------------------------------------------
# Headless status
# ---------------------------------------------------------------------------

class TestHeadlessStatus:
    def test_valid_marker(self):
        tracked = _make_tracked(baseline=10.0, current=25.0)
        state = AppState(markers=[tracked])
        marker = _make_marker()
        mf = MarkerFile(markers=[marker])

        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.find_marker_file", return_value=Path("/tmp/fakerepo/.autoresearch.yaml")),
            patch("autoresearch.cli.load_markers", return_value=mf),
        ):
            result = runner.invoke(app, ["--headless", "status", "-m", "fakerepo:test-marker"])

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["status"] == "ok"
        assert data["data"]["id"] == "fakerepo:test-marker"
        assert data["data"]["direction"] == "higher"
        assert data["data"]["target_metric"] == 50.0

    def test_nonexistent_marker(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "status", "-m", "nope:nope"])
        assert result.exit_code == 1
        assert "error" in result.output


# ---------------------------------------------------------------------------
# Headless results
# ---------------------------------------------------------------------------

class TestHeadlessResults:
    def test_empty_results(self, tmp_path):
        tracked = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[tracked])

        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "results", "-m", "fakerepo:test-marker"])

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["status"] == "ok"
        assert data["data"] == []

    def test_with_results(self, tmp_path):
        from autoresearch.results import ExperimentResult, append_result, ensure_results_dir

        tracked = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[tracked])
        ensure_results_dir(tmp_path, "test-marker")
        append_result(tmp_path, "test-marker", ExperimentResult(
            commit="abc1234", metric=42.0, guard="pass", status="keep",
            confidence="--", description="test experiment",
        ))

        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "results", "-m", "fakerepo:test-marker"])

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert len(data["data"]) == 1
        assert data["data"][0]["commit"] == "abc1234"

    def test_nonexistent_marker(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "results", "-m", "nope:nope"])
        assert result.exit_code == 1
        assert "error" in result.output


# ---------------------------------------------------------------------------
# Headless ideas
# ---------------------------------------------------------------------------

class TestHeadlessIdeas:
    def test_empty_ideas(self, tmp_path):
        tracked = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[tracked])

        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "ideas", "-m", "fakerepo:test-marker"])

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["status"] == "ok"

    def test_with_ideas(self, tmp_path):
        from autoresearch.ideas import append_idea, create_ideas_template

        tracked = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[tracked])
        create_ideas_template(tmp_path, "test-marker")
        append_idea(tmp_path, "test-marker", "Discarded but Promising", "Try caching approach")

        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "ideas", "-m", "fakerepo:test-marker"])

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert "caching" in data["data"]["ideas"]


# ---------------------------------------------------------------------------
# Headless confidence
# ---------------------------------------------------------------------------

class TestHeadlessConfidence:
    def test_no_data(self, tmp_path):
        tracked = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[tracked])

        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "confidence", "-m", "fakerepo:test-marker"])

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["data"]["confidence_label"] == "--"

    def test_with_baseline_and_current(self, tmp_path):
        tracked = _make_tracked(repo_path=str(tmp_path), baseline=10.0, current=25.0)
        state = AppState(markers=[tracked])

        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "confidence", "-m", "fakerepo:test-marker"])

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["data"]["baseline"] == 10.0
        assert data["data"]["current"] == 25.0


# ---------------------------------------------------------------------------
# Headless add
# ---------------------------------------------------------------------------

class TestHeadlessAdd:
    def test_add_from_repo_path(self, tmp_path):
        # Create a valid marker file
        import yaml
        marker_yaml = {
            "markers": [{
                "name": "speed-test",
                "target": {"mutable": ["main.py"]},
                "metric": {"command": "echo 1", "extract": r"\d+", "direction": "higher", "baseline": 1.0},
                "loop": {"model": "sonnet", "budget_per_experiment": "5m", "max_experiments": 10},
            }]
        }
        (tmp_path / ".autoresearch.yaml").write_text(yaml.dump(marker_yaml))

        with patch("autoresearch.cli.load_state", return_value=AppState()), \
             patch("autoresearch.cli.save_state"):
            result = runner.invoke(app, ["--headless", "add", "--path", str(tmp_path)])

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["status"] == "ok"
        assert len(data["data"]["added"]) == 1

    def test_add_no_marker_file(self, tmp_path):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "add", "--path", str(tmp_path)])
        assert result.exit_code == 1
        assert "error" in result.output


# ---------------------------------------------------------------------------
# Headless detach
# ---------------------------------------------------------------------------

class TestHeadlessDetach:
    def test_detach_existing(self):
        tracked = _make_tracked()
        state = AppState(markers=[tracked])

        with patch("autoresearch.cli.load_state", return_value=state), \
             patch("autoresearch.cli.save_state"):
            result = runner.invoke(app, ["--headless", "detach", "-m", "fakerepo:test-marker"])

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["data"]["detached"] == "fakerepo:test-marker"

    def test_detach_nonexistent(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "detach", "-m", "nope:nope"])
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# Headless skip
# ---------------------------------------------------------------------------

class TestHeadlessSkip:
    def test_skip_active_marker(self):
        tracked = _make_tracked()
        state = AppState(markers=[tracked])

        with patch("autoresearch.cli.load_state", return_value=state), \
             patch("autoresearch.cli.save_state"):
            result = runner.invoke(app, ["--headless", "skip", "-m", "fakerepo:test-marker"])

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["data"]["action"] == "skipped"

    def test_unskip_skipped_marker(self):
        tracked = _make_tracked(status_override=MarkerStatus.SKIP)
        state = AppState(markers=[tracked])

        with patch("autoresearch.cli.load_state", return_value=state), \
             patch("autoresearch.cli.save_state"):
            result = runner.invoke(app, ["--headless", "skip", "-m", "fakerepo:test-marker"])

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["data"]["action"] == "unskipped"

    def test_skip_nonexistent(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "skip", "-m", "nope:nope"])
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# Headless run
# ---------------------------------------------------------------------------

class TestHeadlessPause:
    def test_pause_active_marker(self):
        tracked = _make_tracked()
        state = AppState(markers=[tracked])

        with patch("autoresearch.cli.load_state", return_value=state), \
             patch("autoresearch.cli.save_state"):
            result = runner.invoke(app, ["--headless", "pause", "-m", "fakerepo:test-marker"])

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["data"]["action"] == "paused"

    def test_resume_paused_marker(self):
        tracked = _make_tracked(status_override=MarkerStatus.PAUSED)
        state = AppState(markers=[tracked])

        with patch("autoresearch.cli.load_state", return_value=state), \
             patch("autoresearch.cli.save_state"):
            result = runner.invoke(app, ["--headless", "pause", "-m", "fakerepo:test-marker"])

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["data"]["action"] == "resumed"


class TestHeadlessRun:
    def test_run_no_args(self):
        result = runner.invoke(app, ["--headless", "run"])
        assert result.exit_code == 2

    def test_run_nonexistent_marker(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "run", "-m", "nope:nope"])
        assert result.exit_code == 1

    def test_run_marker_success(self):
        from autoresearch.engine import RunResult

        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        marker = _make_marker()
        mf = MarkerFile(markers=[marker])
        mock_result = RunResult(
            marker_name="test-marker",
            experiments=5, kept=3, discarded=2, crashed=0,
            final_metric=42.0, final_confidence=1.5,
            final_status="active", branch="autoresearch/test-marker-mar30",
            worktree_path="/tmp/wt",
        )

        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.find_marker_file", return_value=Path("/tmp/fakerepo/.autoresearch.yaml")),
            patch("autoresearch.cli.load_markers", return_value=mf),
            patch("autoresearch.cli.get_effective_status", return_value=MarkerStatus.ACTIVE),
            patch("autoresearch.engine.get_agent_runner"),
            patch("autoresearch.engine.run_marker", return_value=mock_result),
        ):
            result = runner.invoke(app, ["--headless", "run", "-m", "fakerepo:test-marker"])

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["status"] == "ok"
        assert data["data"][0]["experiments"] == 5
        assert data["data"][0]["kept"] == 3


# ---------------------------------------------------------------------------
# Headless no command
# ---------------------------------------------------------------------------

class TestHeadlessNoCommand:
    def test_exits_code_2(self):
        result = runner.invoke(app, ["--headless"])
        assert result.exit_code == 2
        assert "error" in result.output


# ---------------------------------------------------------------------------
# Interactive mode
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Daemon subcommands
# ---------------------------------------------------------------------------

class TestDaemonStatus:
    def test_headless_status_stopped(self):
        with (
            patch("autoresearch.cli.load_state", return_value=AppState()),
            patch("autoresearch.daemon.read_pid", return_value=None),
            patch("autoresearch.daemon.check_stale_pid", return_value=False),
        ):
            result = runner.invoke(app, ["--headless", "daemon", "status"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["data"]["running"] is False

    def test_headless_status_running(self):
        import os
        state = AppState()
        state.daemon.running = True
        state.daemon.pid = os.getpid()
        state.daemon.started_at = "2026-03-30T01:00:00+00:00"

        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.daemon.read_pid", return_value=os.getpid()),
            patch("autoresearch.daemon.check_stale_pid", return_value=False),
            patch("autoresearch.daemon.is_pid_alive", return_value=True),
        ):
            result = runner.invoke(app, ["--headless", "daemon", "status"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["data"]["running"] is True


class TestDaemonStop:
    def test_headless_stop_nothing_running(self):
        with patch("autoresearch.daemon.stop_daemon", return_value=False):
            result = runner.invoke(app, ["--headless", "daemon", "stop"])
        assert result.exit_code == 1

    def test_headless_stop_success(self):
        with patch("autoresearch.daemon.stop_daemon", return_value=True):
            result = runner.invoke(app, ["--headless", "daemon", "stop"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["data"]["action"] == "stopped"


class TestDaemonStart:
    def test_headless_already_running(self):
        import os
        with (
            patch("autoresearch.daemon.check_stale_pid"),
            patch("autoresearch.daemon.read_pid", return_value=os.getpid()),
            patch("autoresearch.daemon.is_pid_alive", return_value=True),
        ):
            result = runner.invoke(app, ["--headless", "daemon", "start"])
        assert result.exit_code == 1

    def test_headless_start_success(self):
        with (
            patch("autoresearch.daemon.check_stale_pid"),
            patch("autoresearch.daemon.read_pid", return_value=None),
            patch("autoresearch.daemon.daemonize", return_value=12345),
        ):
            result = runner.invoke(app, ["--headless", "daemon", "start"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["data"]["pid"] == 12345


class TestDaemonLogs:
    def test_headless_no_log_file(self):
        with patch("autoresearch.daemon.LOG_PATH", Path("/tmp/nonexistent.log")):
            result = runner.invoke(app, ["--headless", "daemon", "logs"])
        assert result.exit_code == 1

    def test_headless_reads_log(self, tmp_path):
        log_file = tmp_path / "daemon.log"
        log_file.write_text("line1\nline2\nline3\n")
        with patch("autoresearch.daemon.LOG_PATH", log_file):
            result = runner.invoke(app, ["--headless", "daemon", "logs", "-n", "2"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["data"]["lines"] == ["line2", "line3"]


class TestInteractiveMode:
    def test_quit_immediately(self):
        with (
            patch("autoresearch.cli.load_state", return_value=AppState()),
            patch("autoresearch.cli.find_marker_file", return_value=None),
        ):
            result = runner.invoke(app, [], input="q\n")
        assert result.exit_code == 0

    def test_shows_no_markers_message(self):
        with (
            patch("autoresearch.cli.load_state", return_value=AppState()),
            patch("autoresearch.cli.find_marker_file", return_value=None),
        ):
            result = runner.invoke(app, [], input="q\n")
        assert "No markers tracked" in result.stdout

    def test_shows_marker_table(self):
        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        marker = _make_marker()
        mf = MarkerFile(markers=[marker])

        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.find_marker_file", return_value=Path("/tmp/fakerepo/.autoresearch.yaml")),
            patch("autoresearch.cli.load_markers", return_value=mf),
        ):
            result = runner.invoke(app, [], input="q\n")

        assert "fakerepo" in result.stdout or "test-marker" in result.stdout

    def test_select_marker_and_back(self):
        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        marker = _make_marker()
        mf = MarkerFile(markers=[marker])

        def find_marker_side_effect(path):
            # Return None for CWD (home mode), marker file for tracked repo
            if str(path) == "/tmp/fakerepo":
                return Path("/tmp/fakerepo/.autoresearch.yaml")
            return None

        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.find_marker_file", side_effect=find_marker_side_effect),
            patch("autoresearch.cli.load_markers", return_value=mf),
            patch("autoresearch.cli.get_effective_status", return_value=MarkerStatus.ACTIVE),
        ):
            # Select marker 1, then quit submenu, then quit main
            result = runner.invoke(app, [], input="1\nq\nq\n")

        assert result.exit_code == 0
