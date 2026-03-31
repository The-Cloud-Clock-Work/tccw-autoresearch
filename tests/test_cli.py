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


# ---------------------------------------------------------------------------
# Headless init
# ---------------------------------------------------------------------------

class TestHeadlessInit:
    def test_init_creates_config(self, tmp_path):
        with (
            patch("autoresearch.agent_profile.init_autoresearch_dir", return_value=tmp_path / ".autoresearch"),
        ):
            result = runner.invoke(app, ["--headless", "init", "--path", str(tmp_path)])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["status"] == "ok"
        assert data["data"]["config_created"] is True

    def test_init_skips_existing_config(self, tmp_path):
        ar_dir = tmp_path / ".autoresearch"
        ar_dir.mkdir()
        config_path = ar_dir / "config.yaml"
        config_path.write_text("markers: []")

        with (
            patch("autoresearch.agent_profile.init_autoresearch_dir", return_value=ar_dir),
        ):
            result = runner.invoke(app, ["--headless", "init", "--path", str(tmp_path)])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["data"]["config_created"] is False


# ---------------------------------------------------------------------------
# Headless finalize
# ---------------------------------------------------------------------------

class TestHeadlessFinalize:
    def test_finalize_nonexistent_marker(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "finalize", "-m", "nope:nope"])
        assert result.exit_code == 1
        assert "error" in result.output

    def test_finalize_no_kept_results(self, tmp_path):
        tracked = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[tracked])

        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.finalize.finalize_marker", return_value=[]),
        ):
            result = runner.invoke(app, ["--headless", "finalize", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["data"]["branches"] == []

    def test_finalize_with_branches(self, tmp_path):
        tracked = _make_tracked(repo_path=str(tmp_path), branch="autoresearch/test-marker-mar31")
        state = AppState(markers=[tracked])
        mock_branches = [{"branch": "finalize/test-marker-001", "description": "Cached results"}]

        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.finalize.finalize_marker", return_value=mock_branches),
        ):
            result = runner.invoke(app, ["--headless", "finalize", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert len(data["data"]["branches"]) == 1
        assert data["data"]["branches"][0]["branch"] == "finalize/test-marker-001"


# ---------------------------------------------------------------------------
# Headless merge
# ---------------------------------------------------------------------------

class TestHeadlessMerge:
    def test_merge_nonexistent_marker(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "merge", "-m", "nope:nope"])
        assert result.exit_code == 1
        assert "error" in result.output

    def test_merge_no_branch(self):
        tracked = _make_tracked(branch=None)
        state = AppState(markers=[tracked])

        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "merge", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 1
        assert "error" in result.output

    def test_merge_success(self):
        tracked = _make_tracked(branch="autoresearch/test-marker-mar31")
        state = AppState(markers=[tracked])

        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.finalize.merge_finalized", return_value="abc1234567890"),
        ):
            result = runner.invoke(app, ["--headless", "merge", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["data"]["merged"] == "autoresearch/test-marker-mar31"
        assert data["data"]["target"] == "main"
        assert data["data"]["commit"] == "abc1234567890"

    def test_merge_with_explicit_branch(self):
        tracked = _make_tracked(branch="autoresearch/test-marker-mar31")
        state = AppState(markers=[tracked])

        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.finalize.merge_finalized", return_value="def0987654321"),
        ):
            result = runner.invoke(app, [
                "--headless", "merge", "-m", "fakerepo:test-marker",
                "--branch", "finalize/custom-branch", "--target", "dev",
            ])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["data"]["merged"] == "finalize/custom-branch"
        assert data["data"]["target"] == "dev"

    def test_merge_failure(self):
        tracked = _make_tracked(branch="autoresearch/test-marker-mar31")
        state = AppState(markers=[tracked])

        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.finalize.merge_finalized", side_effect=RuntimeError("conflict")),
        ):
            result = runner.invoke(app, ["--headless", "merge", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 1
        assert "error" in result.output


# ---------------------------------------------------------------------------
# Headless run --repo mode
# ---------------------------------------------------------------------------

class TestHeadlessRunRepo:
    def test_run_repo_not_found(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "run", "--repo", "nonexistent"])
        assert result.exit_code == 1
        assert "error" in result.output

    def test_run_repo_skips_non_active(self):
        tracked = _make_tracked(repo_path="/tmp/fakerepo")
        state = AppState(markers=[tracked])
        marker = _make_marker(status=MarkerStatus.SKIP)
        mf = MarkerFile(markers=[marker])

        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.find_marker_file", return_value=Path("/tmp/fakerepo/.autoresearch.yaml")),
            patch("autoresearch.cli.load_markers", return_value=mf),
            patch("autoresearch.cli.get_effective_status", return_value=MarkerStatus.SKIP),
        ):
            result = runner.invoke(app, ["--headless", "run", "--repo", "fakerepo"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["data"] == []

    def test_run_repo_success(self):
        from autoresearch.engine import RunResult

        tracked = _make_tracked(repo_path="/tmp/fakerepo")
        state = AppState(markers=[tracked])
        marker = _make_marker()
        mf = MarkerFile(markers=[marker])
        mock_result = RunResult(
            marker_name="test-marker",
            experiments=3, kept=2, discarded=1, crashed=0,
            final_metric=30.0, final_confidence=1.2,
            final_status="active", branch="autoresearch/test-marker-mar31",
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
            result = runner.invoke(app, ["--headless", "run", "--repo", "fakerepo"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert len(data["data"]) == 1
        assert data["data"][0]["kept"] == 2


# ---------------------------------------------------------------------------
# Non-headless (interactive) CLI paths
# ---------------------------------------------------------------------------

class TestInteractiveList:
    def test_empty_state_prints_message(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["list"])
        assert result.exit_code == 0
        assert "No markers" in result.output

    def test_with_markers_renders_table(self):
        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        marker = _make_marker()
        mf = MarkerFile(markers=[marker])

        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.find_marker_file", return_value=Path("/tmp/fakerepo/.autoresearch.yaml")),
            patch("autoresearch.cli.load_markers", return_value=mf),
        ):
            result = runner.invoke(app, ["list"])
        assert result.exit_code == 0


class TestInteractiveStatus:
    def test_nonexistent_marker_exits_1(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["status", "-m", "missing:marker"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_valid_marker_prints_fields(self):
        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        marker = _make_marker()
        mf = MarkerFile(markers=[marker])

        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.find_marker_file", return_value=Path("/tmp/fakerepo/.autoresearch.yaml")),
            patch("autoresearch.cli.load_markers", return_value=mf),
        ):
            result = runner.invoke(app, ["status", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0
        assert "id" in result.output


class TestInteractiveResults:
    def test_nonexistent_marker_exits_1(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["results", "-m", "missing:marker"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_no_results_prints_message(self):
        tracked = _make_tracked()
        state = AppState(markers=[tracked])

        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.results.read_results", return_value=[]),
        ):
            result = runner.invoke(app, ["results", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0
        assert "No results" in result.output


class TestInteractiveIdeas:
    def test_nonexistent_marker_exits_1(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["ideas", "-m", "missing:marker"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_empty_ideas_prints_message(self):
        tracked = _make_tracked()
        state = AppState(markers=[tracked])

        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.ideas.read_ideas", return_value=""),
        ):
            result = runner.invoke(app, ["ideas", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0
        assert "No ideas" in result.output

    def test_with_ideas_prints_content(self):
        tracked = _make_tracked()
        state = AppState(markers=[tracked])

        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.ideas.read_ideas", return_value="idea 1\nidea 2"),
        ):
            result = runner.invoke(app, ["ideas", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0
        assert "idea" in result.output


class TestInteractiveConfidence:
    def test_nonexistent_marker_exits_1(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["confidence", "-m", "missing:marker"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_with_confidence_score_prints(self):
        tracked = _make_tracked(baseline=10.0, current=20.0)
        state = AppState(markers=[tracked])

        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.results.read_results", return_value=[]),
            patch("autoresearch.results.get_kept_metrics", return_value=[10.0, 20.0]),
            patch("autoresearch.metrics.compute_confidence", return_value=1.5),
            patch("autoresearch.metrics.confidence_label", return_value="high"),
        ):
            result = runner.invoke(app, ["confidence", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0


class TestInteractiveAdd:
    def test_no_marker_file_exits_1(self, tmp_path):
        with patch("autoresearch.cli.find_marker_file", return_value=None):
            result = runner.invoke(app, ["add", "--path", str(tmp_path)])
        assert result.exit_code == 1
        assert "No .autoresearch.yaml" in result.output

    def test_bad_marker_file_exits_1(self, tmp_path):
        with (
            patch("autoresearch.cli.find_marker_file", return_value=tmp_path / ".autoresearch.yaml"),
            patch("autoresearch.cli.load_markers", side_effect=ValueError("bad yaml")),
        ):
            result = runner.invoke(app, ["add", "--path", str(tmp_path)])
        assert result.exit_code == 1
        assert "Error" in result.output

    def test_success_prints_registered(self, tmp_path):
        marker = _make_marker()
        mf = MarkerFile(markers=[marker])

        with (
            patch("autoresearch.cli.find_marker_file", return_value=tmp_path / ".autoresearch.yaml"),
            patch("autoresearch.cli.load_markers", return_value=mf),
            patch("autoresearch.cli.load_state", return_value=AppState()),
            patch("autoresearch.cli.track_marker", return_value=_make_tracked()),
            patch("autoresearch.cli.save_state"),
        ):
            result = runner.invoke(app, ["add", "--path", str(tmp_path)])
        assert result.exit_code == 0
        assert "Registered" in result.output


class TestInteractiveDetach:
    def test_nonexistent_marker_exits_1(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["detach", "-m", "missing:marker"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_success_prints_detached(self):
        tracked = _make_tracked()
        state = AppState(markers=[tracked])

        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.save_state"),
        ):
            result = runner.invoke(app, ["detach", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0
        assert "Detached" in result.output


class TestInteractiveSkip:
    def test_nonexistent_marker_exits_1(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["skip", "-m", "missing:marker"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_skip_active_prints_skipped(self):
        tracked = _make_tracked()
        state = AppState(markers=[tracked])

        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.save_state"),
        ):
            result = runner.invoke(app, ["skip", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0
        assert "skipped" in result.output.lower()


class TestInteractivePause:
    def test_nonexistent_marker_exits_1(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["pause", "-m", "missing:marker"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_pause_active_prints_paused(self):
        tracked = _make_tracked()
        state = AppState(markers=[tracked])

        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.save_state"),
        ):
            result = runner.invoke(app, ["pause", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0
        assert "paused" in result.output.lower()


class TestInteractiveRun:
    def test_no_args_exits_2(self):
        result = runner.invoke(app, ["run"])
        assert result.exit_code == 2

    def test_nonexistent_marker_exits_1(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["run", "-m", "missing:marker"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_no_markers_for_repo_exits_1(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["run", "--repo", "norepo"])
        assert result.exit_code == 1

    def test_run_success_prints_summary(self):
        from autoresearch.engine import RunResult

        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        marker = _make_marker()
        mf = MarkerFile(markers=[marker])
        mock_result = RunResult(
            marker_name="test-marker",
            experiments=2, kept=1, discarded=1, crashed=0,
            final_metric=25.0, final_confidence=1.0,
            final_status="active", branch=None, worktree_path=None,
        )

        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.find_marker_file", return_value=Path("/tmp/fakerepo/.autoresearch.yaml")),
            patch("autoresearch.cli.load_markers", return_value=mf),
            patch("autoresearch.engine.get_agent_runner"),
            patch("autoresearch.engine.run_marker", return_value=mock_result),
        ):
            result = runner.invoke(app, ["run", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0
        assert "experiments" in result.output

    def test_run_engine_error_prints_error(self):
        from autoresearch.engine import EngineError

        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        marker = _make_marker()
        mf = MarkerFile(markers=[marker])

        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.find_marker_file", return_value=Path("/tmp/fakerepo/.autoresearch.yaml")),
            patch("autoresearch.cli.load_markers", return_value=mf),
            patch("autoresearch.engine.get_agent_runner"),
            patch("autoresearch.engine.run_marker", side_effect=EngineError("boom")),
        ):
            result = runner.invoke(app, ["run", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0
        assert "boom" in result.output


class TestInteractiveFinalize:
    def test_nonexistent_marker_exits_1(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["finalize", "-m", "missing:marker"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_no_branches_prints_message(self):
        tracked = _make_tracked()
        state = AppState(markers=[tracked])

        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.results.read_results", return_value=[]),
            patch("autoresearch.finalize.finalize_marker", return_value=[]),
        ):
            result = runner.invoke(app, ["finalize", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0
        assert "No kept" in result.output

    def test_with_branches_prints_each(self):
        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        branches = [{"branch": "autoresearch/br1", "description": "desc1"}]

        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.results.read_results", return_value=[]),
            patch("autoresearch.finalize.finalize_marker", return_value=branches),
        ):
            result = runner.invoke(app, ["finalize", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0
        assert "br1" in result.output


class TestInteractiveMerge:
    def test_nonexistent_marker_exits_1(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["merge", "-m", "missing:marker"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_no_branch_exits_1(self):
        tracked = _make_tracked()
        state = AppState(markers=[tracked])

        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["merge", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 1
        assert "No branch" in result.output

    def test_success_prints_merged(self):
        tracked = _make_tracked(branch="autoresearch/test-marker-mar31")
        state = AppState(markers=[tracked])

        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.finalize.merge_finalized", return_value="abc1234567"),
        ):
            result = runner.invoke(app, ["merge", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0
        assert "Merged" in result.output

    def test_merge_exception_exits_1(self):
        tracked = _make_tracked(branch="autoresearch/test-marker-mar31")
        state = AppState(markers=[tracked])

        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.finalize.merge_finalized", side_effect=RuntimeError("conflict")),
        ):
            result = runner.invoke(app, ["merge", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 1
        assert "conflict" in result.output


class TestInteractiveInit:
    def test_init_new_prints_initialized(self, tmp_path):
        with (
            patch("autoresearch.agent_profile.init_autoresearch_dir", return_value=tmp_path / ".autoresearch"),
        ):
            result = runner.invoke(app, ["init", "--path", str(tmp_path)])
        assert result.exit_code == 0
        assert "Initialized" in result.output or "Synced" in result.output or "Config" in result.output


class TestResolveMarkerDataEdgeCases:
    def test_load_markers_exception_returns_nones(self):
        tracked = _make_tracked()
        with (
            patch("autoresearch.cli.find_marker_file", return_value=Path("/tmp/fakerepo/.autoresearch.yaml")),
            patch("autoresearch.cli.load_markers", side_effect=ValueError("bad")),
        ):
            from autoresearch.cli import _resolve_marker_data
            mf, m, eff = _resolve_marker_data(tracked)
        assert mf is None
        assert m is None
        assert eff is None

    def test_marker_not_found_returns_nones(self):
        tracked = _make_tracked(marker_name="nonexistent")
        mf = MarkerFile(markers=[_make_marker("other")])
        with (
            patch("autoresearch.cli.find_marker_file", return_value=Path("/tmp/fakerepo/.autoresearch.yaml")),
            patch("autoresearch.cli.load_markers", return_value=mf),
        ):
            from autoresearch.cli import _resolve_marker_data
            result = _resolve_marker_data(tracked)
        assert result == (None, None, None)


class TestRenderMarkerTableValueError:
    def test_invalid_status_uses_raw_string(self):
        from autoresearch.cli import _render_marker_table
        markers_data = [{"id": "r:m", "repo": "r", "marker": "m", "status": "invalid_status", "last_run": None, "current": None}]
        _render_marker_table(markers_data)


class TestDaemonCommandsNonHeadless:
    def test_daemon_start_already_running(self):
        with (
            patch("autoresearch.daemon.check_stale_pid"),
            patch("autoresearch.daemon.read_pid", return_value=12345),
            patch("autoresearch.daemon.is_pid_alive", return_value=True),
        ):
            result = runner.invoke(app, ["daemon", "start"])
        assert result.exit_code == 1
        assert "already running" in result.output.lower()

    def test_daemon_start_runtime_error(self):
        with (
            patch("autoresearch.daemon.check_stale_pid"),
            patch("autoresearch.daemon.read_pid", return_value=None),
            patch("autoresearch.daemon.is_pid_alive", return_value=False),
            patch("autoresearch.daemon.daemonize", side_effect=RuntimeError("not supported on Windows")),
        ):
            result = runner.invoke(app, ["daemon", "start"])
        assert result.exit_code == 1
        assert "not supported" in result.output.lower() or "Windows" in result.output

    def test_daemon_start_success(self):
        with (
            patch("autoresearch.daemon.check_stale_pid"),
            patch("autoresearch.daemon.read_pid", return_value=None),
            patch("autoresearch.daemon.is_pid_alive", return_value=False),
            patch("autoresearch.daemon.daemonize", return_value=99999),
        ):
            result = runner.invoke(app, ["daemon", "start"])
        assert result.exit_code == 0
        assert "99999" in result.output

    def test_daemon_stop_nothing_running(self):
        with patch("autoresearch.daemon.stop_daemon", return_value=False):
            result = runner.invoke(app, ["daemon", "stop"])
        assert result.exit_code == 0
        assert "No daemon" in result.output

    def test_daemon_stop_success(self):
        with patch("autoresearch.daemon.stop_daemon", return_value=True):
            result = runner.invoke(app, ["daemon", "stop"])
        assert result.exit_code == 0
        assert "stopped" in result.output.lower()

    def test_daemon_status_stopped_no_scheduled(self):
        with (
            patch("autoresearch.daemon.check_stale_pid"),
            patch("autoresearch.daemon.read_pid", return_value=None),
            patch("autoresearch.daemon.is_pid_alive", return_value=False),
            patch("autoresearch.cli.load_state", return_value=AppState()),
        ):
            result = runner.invoke(app, ["daemon", "status"])
        assert result.exit_code == 0
        assert "stopped" in result.output.lower() or "No scheduled" in result.output

    def test_daemon_status_running_with_scheduled(self):
        from autoresearch.marker import Schedule

        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        marker = _make_marker()
        marker.schedule = Schedule(type="cron", cron="0 * * * *")
        mf = MarkerFile(markers=[marker])

        with (
            patch("autoresearch.daemon.check_stale_pid"),
            patch("autoresearch.daemon.read_pid", return_value=1234),
            patch("autoresearch.daemon.is_pid_alive", return_value=True),
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.find_marker_file", return_value=Path("/tmp/fakerepo/.autoresearch.yaml")),
            patch("autoresearch.cli.load_markers", return_value=mf),
        ):
            result = runner.invoke(app, ["daemon", "status"])
        assert result.exit_code == 0

    def test_daemon_logs_no_file(self):
        with patch("autoresearch.daemon.LOG_PATH") as mock_path:
            mock_path.is_file.return_value = False
            result = runner.invoke(app, ["daemon", "logs"])
        assert result.exit_code == 1
        assert "No log" in result.output

    def test_daemon_logs_reads_file(self, tmp_path):
        log_file = tmp_path / "daemon.log"
        log_file.write_text("line1\nline2\nline3\n")

        with patch("autoresearch.daemon.LOG_PATH", log_file):
            result = runner.invoke(app, ["daemon", "logs"])
        assert result.exit_code == 0
        assert "line1" in result.output

    def test_daemon_logs_follow_not_headless(self, tmp_path):
        log_file = tmp_path / "daemon.log"
        log_file.write_text("content\n")

        with (
            patch("autoresearch.daemon.LOG_PATH", log_file),
            patch("subprocess.run"),
        ):
            result = runner.invoke(app, ["daemon", "logs", "--follow"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Headless command paths - missing coverage
# ---------------------------------------------------------------------------

class TestHeadlessIdeasNotFound:
    def test_ideas_headless_marker_not_found(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "ideas", "-m", "nope:nope"])
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["status"] == "error"


class TestHeadlessConfidenceNotFound:
    def test_confidence_headless_marker_not_found(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "confidence", "-m", "nope:nope"])
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["status"] == "error"


class TestHeadlessPauseNotFound:
    def test_pause_headless_marker_not_found(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "pause", "-m", "nope:nope"])
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["status"] == "error"


class TestHeadlessAddBadFile:
    def test_add_headless_load_markers_error(self, tmp_path):
        with (
            patch("autoresearch.cli.find_marker_file", return_value=tmp_path / ".autoresearch.yaml"),
            patch("autoresearch.cli.load_markers", side_effect=ValueError("bad yaml")),
        ):
            result = runner.invoke(app, ["--headless", "add", "--path", str(tmp_path)])
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["status"] == "error"


class TestNonHeadlessResultsWithData:
    def test_results_cmd_non_headless_with_results(self, tmp_path):
        from autoresearch.results import ExperimentResult
        tracked = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[tracked])
        mock_results = [
            ExperimentResult(commit="abc123", metric=42.0, guard="pass", status="keep",
                             confidence="1.5", description="improved"),
        ]
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.results.read_results", return_value=mock_results),
        ):
            result = runner.invoke(app, ["results", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0


class TestNonHeadlessRunMarkerConfigMissing:
    def test_run_non_headless_marker_config_none(self):
        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli._resolve_marker_data", return_value=(None, None, None)),
        ):
            result = runner.invoke(app, ["run", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0
        assert "Cannot load" in result.output or "error" in result.output.lower()


class TestRunWithModelOption:
    def test_run_headless_with_model_override(self):
        from autoresearch.engine import RunResult
        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        marker = _make_marker()
        mf = MarkerFile(markers=[marker])
        mock_result = RunResult(
            marker_name="test-marker",
            experiments=1, kept=1, discarded=0, crashed=0,
            final_metric=20.0, final_confidence=1.0,
            final_status="active", branch=None, worktree_path=None,
        )
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.find_marker_file", return_value=Path("/tmp/fakerepo/.autoresearch.yaml")),
            patch("autoresearch.cli.load_markers", return_value=mf),
            patch("autoresearch.engine.get_agent_runner"),
            patch("autoresearch.engine.run_marker", return_value=mock_result),
        ):
            result = runner.invoke(app, ["--headless", "run", "-m", "fakerepo:test-marker", "--model", "opus"])
        assert result.exit_code == 0


class TestDaemonStartHeadlessError:
    def test_daemon_start_headless_runtime_error(self):
        with (
            patch("autoresearch.daemon.check_stale_pid"),
            patch("autoresearch.daemon.read_pid", return_value=None),
            patch("autoresearch.daemon.is_pid_alive", return_value=False),
            patch("autoresearch.daemon.daemonize", side_effect=RuntimeError("Windows not supported")),
        ):
            result = runner.invoke(app, ["--headless", "daemon", "start"])
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["status"] == "error"
        assert "Windows" in data.get("message", data.get("error", ""))


class TestDaemonStartWithConfigPath:
    def test_daemon_start_loads_config_when_config_path_set(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("daemon:\n  max_concurrent: 2\n")
        from autoresearch.config import GlobalConfig
        mock_config = GlobalConfig()
        with (
            patch("autoresearch.daemon.check_stale_pid"),
            patch("autoresearch.daemon.read_pid", return_value=None),
            patch("autoresearch.daemon.is_pid_alive", return_value=False),
            patch("autoresearch.daemon.daemonize", return_value=42424),
            patch("autoresearch.config.load_config", return_value=mock_config),
        ):
            result = runner.invoke(app, [
                "--headless", "--config", str(config_file), "daemon", "start",
            ])
        assert result.exit_code == 0


class TestDaemonStatusNonHeadlessStartedAt:
    def test_daemon_status_prints_started_at(self):
        from autoresearch.state import DaemonState
        state = AppState()
        state.daemon = DaemonState(running=True, pid=1234, started_at="2026-03-31T00:00:00+00:00")
        with (
            patch("autoresearch.daemon.check_stale_pid"),
            patch("autoresearch.daemon.read_pid", return_value=1234),
            patch("autoresearch.daemon.is_pid_alive", return_value=True),
            patch("autoresearch.cli.load_state", return_value=state),
        ):
            result = runner.invoke(app, ["daemon", "status"])
        assert result.exit_code == 0
        assert "2026" in result.output

    def test_daemon_status_scheduled_with_last_run(self):
        from autoresearch.marker import Schedule
        tracked = _make_tracked(last_run="2026-03-31T01:00:00+00:00")
        state = AppState(markers=[tracked])
        marker = _make_marker()
        marker.schedule = Schedule(type="cron", cron="0 3 * * *")
        mf = MarkerFile(markers=[marker])
        with (
            patch("autoresearch.daemon.check_stale_pid"),
            patch("autoresearch.daemon.read_pid", return_value=None),
            patch("autoresearch.daemon.is_pid_alive", return_value=False),
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.find_marker_file", return_value=Path("/tmp/fakerepo/.autoresearch.yaml")),
            patch("autoresearch.cli.load_markers", return_value=mf),
        ):
            result = runner.invoke(app, ["daemon", "status"])
        assert result.exit_code == 0

    def test_daemon_status_scheduled_invalid_cron(self):
        from autoresearch.marker import Schedule
        tracked = _make_tracked(last_run="2026-03-31T01:00:00")
        state = AppState(markers=[tracked])
        marker = _make_marker()
        marker.schedule = Schedule(type="cron", cron="invalid cron expr")
        mf = MarkerFile(markers=[marker])
        with (
            patch("autoresearch.daemon.check_stale_pid"),
            patch("autoresearch.daemon.read_pid", return_value=None),
            patch("autoresearch.daemon.is_pid_alive", return_value=False),
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.find_marker_file", return_value=Path("/tmp/fakerepo/.autoresearch.yaml")),
            patch("autoresearch.cli.load_markers", return_value=mf),
        ):
            result = runner.invoke(app, ["daemon", "status"])
        assert result.exit_code == 0


class TestDaemonLogsFollowHeadless:
    def test_follow_flag_headless_exits_2(self, tmp_path):
        log_file = tmp_path / "daemon.log"
        log_file.write_text("log content\n")
        with patch("autoresearch.daemon.LOG_PATH", log_file):
            result = runner.invoke(app, ["--headless", "daemon", "logs", "--follow"])
        assert result.exit_code == 2


# ---------------------------------------------------------------------------
# Private interactive helper functions - direct unit tests
# ---------------------------------------------------------------------------

class TestPrivateShowStatus:
    def test_prints_all_fields(self):
        from autoresearch.cli import _show_status_interactive
        tracked = _make_tracked(baseline=5.0, current=15.0, branch="autoresearch/test")
        marker = _make_marker()
        _show_status_interactive(tracked, marker, MarkerStatus.ACTIVE)

    def test_prints_with_none_marker(self):
        from autoresearch.cli import _show_status_interactive
        tracked = _make_tracked()
        _show_status_interactive(tracked, None, None)


class TestPrivateShowResults:
    def test_no_results(self):
        from autoresearch.cli import _show_results_interactive
        tracked = _make_tracked()
        with patch("autoresearch.results.read_results", return_value=[]):
            _show_results_interactive(tracked)

    def test_with_results_renders_table(self, tmp_path):
        from autoresearch.cli import _show_results_interactive
        from autoresearch.results import ExperimentResult
        tracked = _make_tracked(repo_path=str(tmp_path))
        results = [
            ExperimentResult(commit="a1b2c3d", metric=50.0, guard="pass",
                             status="keep", confidence="2.0", description="test"),
            ExperimentResult(commit="e5f6g7h", metric=55.0, guard="pass",
                             status="keep", confidence="--", description="better"),
        ]
        with patch("autoresearch.results.read_results", return_value=results):
            _show_results_interactive(tracked)


class TestPrivateToggleSkip:
    def test_skip_active_marker(self):
        from unittest.mock import MagicMock
        from autoresearch.cli import _toggle_skip
        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        marker = _make_marker()
        ctx = MagicMock()
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.save_state"),
        ):
            _toggle_skip(ctx, tracked, marker)
        assert state.markers[0].status_override == MarkerStatus.SKIP

    def test_unskip_skipped_marker(self):
        from unittest.mock import MagicMock
        from autoresearch.cli import _toggle_skip
        tracked = _make_tracked(status_override=MarkerStatus.SKIP)
        state = AppState(markers=[tracked])
        marker = _make_marker()
        ctx = MagicMock()
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.save_state"),
        ):
            _toggle_skip(ctx, tracked, marker)
        assert state.markers[0].status_override is None

    def test_missing_tracked_returns_early(self):
        from unittest.mock import MagicMock
        from autoresearch.cli import _toggle_skip
        tracked = _make_tracked(marker_id="missing:marker")
        state = AppState(markers=[])
        marker = _make_marker()
        ctx = MagicMock()
        with patch("autoresearch.cli.load_state", return_value=state):
            _toggle_skip(ctx, tracked, marker)  # no crash


class TestPrivateTogglePause:
    def test_pause_active_marker(self):
        from unittest.mock import MagicMock
        from autoresearch.cli import _toggle_pause
        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        marker = _make_marker()
        ctx = MagicMock()
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.save_state"),
        ):
            _toggle_pause(ctx, tracked, marker)
        assert state.markers[0].status_override == MarkerStatus.PAUSED

    def test_resume_paused_marker(self):
        from unittest.mock import MagicMock
        from autoresearch.cli import _toggle_pause
        tracked = _make_tracked(status_override=MarkerStatus.PAUSED)
        state = AppState(markers=[tracked])
        marker = _make_marker()
        ctx = MagicMock()
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.save_state"),
        ):
            _toggle_pause(ctx, tracked, marker)
        assert state.markers[0].status_override is None

    def test_missing_tracked_returns_early(self):
        from unittest.mock import MagicMock
        from autoresearch.cli import _toggle_pause
        tracked = _make_tracked(marker_id="missing:marker")
        state = AppState(markers=[])
        marker = _make_marker()
        ctx = MagicMock()
        with patch("autoresearch.cli.load_state", return_value=state):
            _toggle_pause(ctx, tracked, marker)


class TestPrivateEditConfig:
    def test_no_marker_file_prints_error(self, capsys):
        from autoresearch.cli import _edit_config
        tracked = _make_tracked()
        with patch("autoresearch.cli.find_marker_file", return_value=None):
            _edit_config(tracked)

    def test_with_marker_file_runs_editor(self, tmp_path):
        from autoresearch.cli import _edit_config
        tracked = _make_tracked(repo_path=str(tmp_path))
        marker_file = tmp_path / ".autoresearch.yaml"
        with (
            patch("autoresearch.cli.find_marker_file", return_value=marker_file),
            patch("subprocess.run") as mock_run,
        ):
            _edit_config(tracked)
        mock_run.assert_called_once()


class TestPrivateShowBranch:
    def test_no_branch_prints_message(self):
        from autoresearch.cli import _show_branch
        tracked = _make_tracked(branch=None)
        _show_branch(tracked)

    def test_branch_with_git_log_success(self, tmp_path):
        from unittest.mock import MagicMock
        from autoresearch.cli import _show_branch
        tracked = _make_tracked(repo_path=str(tmp_path), branch="autoresearch/test")
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "abc1234 Add test\ndef5678 Fix bug\n"
        with patch("subprocess.run", return_value=mock_result):
            _show_branch(tracked)

    def test_branch_with_git_log_empty(self, tmp_path):
        from unittest.mock import MagicMock
        from autoresearch.cli import _show_branch
        tracked = _make_tracked(repo_path=str(tmp_path), branch="autoresearch/test")
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        with patch("subprocess.run", return_value=mock_result):
            _show_branch(tracked)

    def test_branch_subprocess_exception(self, tmp_path):
        from autoresearch.cli import _show_branch
        tracked = _make_tracked(repo_path=str(tmp_path), branch="autoresearch/test")
        with patch("subprocess.run", side_effect=OSError("not found")):
            _show_branch(tracked)


class TestPrivateShowIdeas:
    def test_empty_ideas(self):
        from autoresearch.cli import _show_ideas_interactive
        tracked = _make_tracked()
        with patch("autoresearch.ideas.read_ideas", return_value=""):
            _show_ideas_interactive(tracked)

    def test_with_ideas_content(self):
        from autoresearch.cli import _show_ideas_interactive
        tracked = _make_tracked()
        with patch("autoresearch.ideas.read_ideas", return_value="idea 1\nidea 2"):
            _show_ideas_interactive(tracked)


class TestPrivateShowConfidence:
    def test_no_baseline_prints_message(self):
        from autoresearch.cli import _show_confidence_interactive
        tracked = _make_tracked(baseline=None, current=None)
        with patch("autoresearch.results.read_results", return_value=[]):
            _show_confidence_interactive(tracked)

    def test_with_baseline_and_score(self):
        from autoresearch.cli import _show_confidence_interactive
        tracked = _make_tracked(baseline=10.0, current=20.0)
        with (
            patch("autoresearch.results.read_results", return_value=[]),
            patch("autoresearch.results.get_kept_metrics", return_value=[10.0, 15.0, 20.0]),
            patch("autoresearch.metrics.compute_confidence", return_value=1.5),
            patch("autoresearch.metrics.confidence_label", return_value="high"),
        ):
            _show_confidence_interactive(tracked)

    def test_with_baseline_no_score(self):
        from autoresearch.cli import _show_confidence_interactive
        tracked = _make_tracked(baseline=10.0, current=20.0)
        with (
            patch("autoresearch.results.read_results", return_value=[]),
            patch("autoresearch.results.get_kept_metrics", return_value=[]),
            patch("autoresearch.metrics.compute_confidence", return_value=None),
            patch("autoresearch.metrics.confidence_label", return_value="low"),
        ):
            _show_confidence_interactive(tracked)


class TestPrivateFinalizeInteractive:
    def test_no_results_prints_message(self):
        from unittest.mock import MagicMock
        from autoresearch.cli import _finalize_interactive
        tracked = _make_tracked()
        ctx = MagicMock()
        with patch("autoresearch.results.read_results", return_value=[]):
            _finalize_interactive(ctx, tracked)

    def test_no_branches_returned(self):
        from unittest.mock import MagicMock
        from autoresearch.results import ExperimentResult
        from autoresearch.cli import _finalize_interactive
        tracked = _make_tracked()
        ctx = MagicMock()
        results = [ExperimentResult(commit="a1", metric=10.0, guard="pass", status="keep", description="x")]
        with (
            patch("autoresearch.results.read_results", return_value=results),
            patch("autoresearch.finalize.finalize_marker", return_value=[]),
        ):
            _finalize_interactive(ctx, tracked)

    def test_with_branches_prints_them(self):
        from unittest.mock import MagicMock
        from autoresearch.results import ExperimentResult
        from autoresearch.cli import _finalize_interactive
        tracked = _make_tracked()
        ctx = MagicMock()
        results = [ExperimentResult(commit="a1", metric=10.0, guard="pass", status="keep", description="x")]
        branches = [{"branch": "finalize/x", "description": "good change"}]
        with (
            patch("autoresearch.results.read_results", return_value=results),
            patch("autoresearch.finalize.finalize_marker", return_value=branches),
        ):
            _finalize_interactive(ctx, tracked)


class TestPrivateMergeInteractive:
    def test_no_branch_prints_message(self):
        from unittest.mock import MagicMock
        from autoresearch.cli import _merge_interactive
        tracked = _make_tracked(branch=None)
        ctx = MagicMock()
        _merge_interactive(ctx, tracked)

    def test_merge_success(self):
        from unittest.mock import MagicMock
        from autoresearch.cli import _merge_interactive
        tracked = _make_tracked(branch="autoresearch/test-mar31")
        ctx = MagicMock()
        with (
            patch("rich.prompt.Prompt.ask", return_value="main"),
            patch("autoresearch.finalize.merge_finalized", return_value="abc1234567"),
        ):
            _merge_interactive(ctx, tracked)

    def test_merge_exception_prints_error(self):
        from unittest.mock import MagicMock
        from autoresearch.cli import _merge_interactive
        tracked = _make_tracked(branch="autoresearch/test-mar31")
        ctx = MagicMock()
        with (
            patch("rich.prompt.Prompt.ask", return_value="main"),
            patch("autoresearch.finalize.merge_finalized", side_effect=RuntimeError("conflict")),
        ):
            _merge_interactive(ctx, tracked)


class TestPrivateRunSingleMarker:
    def test_marker_config_none_prints_error(self):
        from unittest.mock import MagicMock
        from autoresearch.cli import _run_single_marker
        tracked = _make_tracked()
        ctx = MagicMock()
        with patch("autoresearch.cli._resolve_marker_data", return_value=(None, None, None)):
            _run_single_marker(ctx, tracked)

    def test_run_success_prints_summary(self):
        from unittest.mock import MagicMock
        from autoresearch.engine import RunResult
        from autoresearch.cli import _run_single_marker
        tracked = _make_tracked()
        ctx = MagicMock()
        marker = _make_marker()
        mf = MarkerFile(markers=[marker])
        mock_result = RunResult(
            marker_name="test-marker",
            experiments=2, kept=1, discarded=1, crashed=0,
            final_metric=30.0, final_confidence=1.2,
            final_status="active", branch=None, worktree_path=None,
        )
        with (
            patch("autoresearch.cli._resolve_marker_data", return_value=(mf, marker, MarkerStatus.ACTIVE)),
            patch("autoresearch.cli.load_state", return_value=AppState()),
            patch("autoresearch.engine.get_agent_runner"),
            patch("autoresearch.engine.run_marker", return_value=mock_result),
        ):
            _run_single_marker(ctx, tracked)

    def test_run_engine_error_prints_error(self):
        from unittest.mock import MagicMock
        from autoresearch.engine import EngineError
        from autoresearch.cli import _run_single_marker
        tracked = _make_tracked()
        ctx = MagicMock()
        marker = _make_marker()
        mf = MarkerFile(markers=[marker])
        with (
            patch("autoresearch.cli._resolve_marker_data", return_value=(mf, marker, MarkerStatus.ACTIVE)),
            patch("autoresearch.cli.load_state", return_value=AppState()),
            patch("autoresearch.engine.get_agent_runner"),
            patch("autoresearch.engine.run_marker", side_effect=EngineError("boom")),
        ):
            _run_single_marker(ctx, tracked)

    def test_run_result_no_metric(self):
        from unittest.mock import MagicMock
        from autoresearch.engine import RunResult
        from autoresearch.cli import _run_single_marker
        tracked = _make_tracked()
        ctx = MagicMock()
        marker = _make_marker()
        mf = MarkerFile(markers=[marker])
        mock_result = RunResult(
            marker_name="test-marker",
            experiments=1, kept=0, discarded=1, crashed=0,
            final_metric=None, final_confidence=None,
            final_status="active", branch=None, worktree_path=None,
        )
        with (
            patch("autoresearch.cli._resolve_marker_data", return_value=(mf, marker, MarkerStatus.ACTIVE)),
            patch("autoresearch.cli.load_state", return_value=AppState()),
            patch("autoresearch.engine.get_agent_runner"),
            patch("autoresearch.engine.run_marker", return_value=mock_result),
        ):
            _run_single_marker(ctx, tracked)


class TestPrivateRunRepoMarkers:
    def test_skips_non_matching_repo(self):
        from unittest.mock import MagicMock
        from autoresearch.cli import _run_repo_markers
        tracked1 = _make_tracked(repo_path="/tmp/repo1", marker_id="repo1:m1")
        tracked1.repo_name = "repo1"
        tracked2 = _make_tracked(repo_path="/tmp/repo2", marker_id="repo2:m2")
        tracked2.repo_name = "repo2"
        state = AppState(markers=[tracked1, tracked2])
        ctx = MagicMock()
        with patch("autoresearch.cli._run_single_marker") as mock_run:
            with patch("autoresearch.cli._resolve_marker_data", return_value=(None, _make_marker(), MarkerStatus.ACTIVE)):
                _run_repo_markers(ctx, state, "repo1")
        assert mock_run.call_count == 1

    def test_skips_non_active_in_repo(self):
        from unittest.mock import MagicMock
        from autoresearch.cli import _run_repo_markers
        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        ctx = MagicMock()
        with (
            patch("autoresearch.cli._resolve_marker_data", return_value=(None, _make_marker(), MarkerStatus.SKIP)),
            patch("autoresearch.cli._run_single_marker") as mock_run,
        ):
            _run_repo_markers(ctx, state, "fakerepo")
        mock_run.assert_not_called()


class TestPrivateActionAdd:
    def test_no_marker_file_prints_error(self, tmp_path):
        from unittest.mock import MagicMock
        from autoresearch.cli import _action_add
        ctx = MagicMock()
        with patch("autoresearch.cli.find_marker_file", return_value=None):
            _action_add(ctx, tmp_path)

    def test_bad_marker_file_prints_error(self, tmp_path):
        from unittest.mock import MagicMock
        from autoresearch.cli import _action_add
        ctx = MagicMock()
        with (
            patch("autoresearch.cli.find_marker_file", return_value=tmp_path / ".autoresearch.yaml"),
            patch("autoresearch.cli.load_markers", side_effect=ValueError("bad")),
        ):
            _action_add(ctx, tmp_path)

    def test_success_registers_markers(self, tmp_path):
        from unittest.mock import MagicMock
        from autoresearch.cli import _action_add
        ctx = MagicMock()
        marker = _make_marker()
        mf = MarkerFile(markers=[marker])
        tracked = _make_tracked()
        with (
            patch("autoresearch.cli.find_marker_file", return_value=tmp_path / ".autoresearch.yaml"),
            patch("autoresearch.cli.load_markers", return_value=mf),
            patch("autoresearch.cli.load_state", return_value=AppState()),
            patch("autoresearch.cli.track_marker", return_value=tracked),
            patch("autoresearch.cli.save_state"),
        ):
            _action_add(ctx, tmp_path)


class TestPrivateActionDetach:
    def test_no_markers_prints_dim(self):
        from unittest.mock import MagicMock
        from autoresearch.cli import _action_detach_interactive
        ctx = MagicMock()
        state = AppState(markers=[])
        _action_detach_interactive(ctx, state)

    def test_detaches_selected_marker(self):
        from unittest.mock import MagicMock
        from autoresearch.cli import _action_detach_interactive
        ctx = MagicMock()
        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        with (
            patch("rich.prompt.Prompt.ask", return_value="1"),
            patch("autoresearch.cli.untrack_marker"),
            patch("autoresearch.cli.save_state"),
        ):
            _action_detach_interactive(ctx, state)


class TestPrivateActionRunSelected:
    def test_no_markers_prints_dim(self):
        from unittest.mock import MagicMock
        from autoresearch.cli import _action_run_selected_interactive
        ctx = MagicMock()
        state = AppState(markers=[])
        _action_run_selected_interactive(ctx, state)

    def test_runs_selected(self):
        from unittest.mock import MagicMock
        from autoresearch.cli import _action_run_selected_interactive
        ctx = MagicMock()
        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        with (
            patch("rich.prompt.Prompt.ask", return_value="1"),
            patch("autoresearch.cli._run_single_marker") as mock_run,
        ):
            _action_run_selected_interactive(ctx, state)
        mock_run.assert_called_once()


class TestPrivateActionRunRepo:
    def test_no_repos_prints_dim(self):
        from unittest.mock import MagicMock
        from autoresearch.cli import _action_run_repo_interactive
        ctx = MagicMock()
        state = AppState(markers=[])
        _action_run_repo_interactive(ctx, state)

    def test_runs_selected_repo(self):
        from unittest.mock import MagicMock
        from autoresearch.cli import _action_run_repo_interactive
        ctx = MagicMock()
        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        with (
            patch("rich.prompt.Prompt.ask", return_value="1"),
            patch("autoresearch.cli._run_repo_markers") as mock_run,
        ):
            _action_run_repo_interactive(ctx, state)
        mock_run.assert_called_once()


class TestPrivateRepoMode:
    def test_load_markers_error_returns_early(self, tmp_path):
        from unittest.mock import MagicMock
        from autoresearch.cli import _repo_mode
        ctx = MagicMock()
        state = AppState(markers=[])
        marker_file = tmp_path / ".autoresearch.yaml"
        with patch("autoresearch.cli.load_markers", side_effect=ValueError("bad yaml")):
            _repo_mode(ctx, state, tmp_path, marker_file)

    def test_all_tracked_renders_table(self, tmp_path):
        from unittest.mock import MagicMock
        from autoresearch.cli import _repo_mode
        ctx = MagicMock()
        tracked = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[tracked])
        marker = _make_marker()
        mf = MarkerFile(markers=[marker])
        with (
            patch("autoresearch.cli.load_markers", return_value=mf),
            patch("autoresearch.cli._resolve_marker_data", return_value=(mf, marker, MarkerStatus.ACTIVE)),
        ):
            _repo_mode(ctx, state, tmp_path, tmp_path / ".autoresearch.yaml")

    def test_untracked_markers_register_when_user_says_yes(self, tmp_path):
        from unittest.mock import MagicMock
        from autoresearch.cli import _repo_mode
        ctx = MagicMock()
        state = AppState(markers=[])
        marker = _make_marker()
        mf = MarkerFile(markers=[marker])
        with (
            patch("autoresearch.cli.load_markers", return_value=mf),
            patch("rich.prompt.Prompt.ask", return_value="y"),
            patch("autoresearch.cli.track_marker", return_value=_make_tracked()),
            patch("autoresearch.cli.save_state"),
        ):
            _repo_mode(ctx, state, tmp_path, tmp_path / ".autoresearch.yaml")

    def test_untracked_markers_skip_when_user_says_no(self, tmp_path):
        from unittest.mock import MagicMock
        from autoresearch.cli import _repo_mode
        ctx = MagicMock()
        state = AppState(markers=[])
        marker = _make_marker()
        mf = MarkerFile(markers=[marker])
        with (
            patch("autoresearch.cli.load_markers", return_value=mf),
            patch("rich.prompt.Prompt.ask", return_value="n"),
        ):
            _repo_mode(ctx, state, tmp_path, tmp_path / ".autoresearch.yaml")


class TestInitCtxWhenNone:
    def test_init_ctx_sets_empty_dict_when_none(self):
        from unittest.mock import MagicMock
        from autoresearch.cli import _init_ctx
        ctx = MagicMock()
        ctx.obj = None
        _init_ctx(ctx)
        assert ctx.obj == {}

    def test_init_ctx_does_not_overwrite_existing(self):
        from unittest.mock import MagicMock
        from autoresearch.cli import _init_ctx
        ctx = MagicMock()
        ctx.obj = {"key": "value"}
        _init_ctx(ctx)
        assert ctx.obj == {"key": "value"}
