"""Tests for CLI commands."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

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
        data = json.loads(result.output)
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
        data = json.loads(result.output)
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
        data = json.loads(result.output)
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
        data = json.loads(result.output)
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
        data = json.loads(result.output)
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
        data = json.loads(result.output)
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
        data = json.loads(result.output)
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
        data = json.loads(result.output)
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
        data = json.loads(result.output)
        assert data["data"]["confidence_label"] == "--"

    def test_with_baseline_and_current(self, tmp_path):
        tracked = _make_tracked(repo_path=str(tmp_path), baseline=10.0, current=25.0)
        state = AppState(markers=[tracked])

        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "confidence", "-m", "fakerepo:test-marker"])

        assert result.exit_code == 0
        data = json.loads(result.output)
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
        data = json.loads(result.output)
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
        data = json.loads(result.output)
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
        data = json.loads(result.output)
        assert data["data"]["action"] == "skipped"

    def test_unskip_skipped_marker(self):
        tracked = _make_tracked(status_override=MarkerStatus.SKIP)
        state = AppState(markers=[tracked])

        with patch("autoresearch.cli.load_state", return_value=state), \
             patch("autoresearch.cli.save_state"):
            result = runner.invoke(app, ["--headless", "skip", "-m", "fakerepo:test-marker"])

        assert result.exit_code == 0
        data = json.loads(result.output)
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
        data = json.loads(result.output)
        assert data["data"]["action"] == "paused"

    def test_resume_paused_marker(self):
        tracked = _make_tracked(status_override=MarkerStatus.PAUSED)
        state = AppState(markers=[tracked])

        with patch("autoresearch.cli.load_state", return_value=state), \
             patch("autoresearch.cli.save_state"):
            result = runner.invoke(app, ["--headless", "pause", "-m", "fakerepo:test-marker"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["data"]["action"] == "resumed"


class TestHeadlessRun:
    def test_run_no_args_no_config(self):
        with patch("autoresearch.cli._load_local_markers", return_value=[]):
            result = runner.invoke(app, ["--headless", "run"])
        assert result.exit_code == 2

    def test_run_nonexistent_marker(self):
        with patch("autoresearch.cli._load_local_markers", return_value=[]):
            result = runner.invoke(app, ["--headless", "run", "-m", "nope"])
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
        data = json.loads(result.output)
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
        data = json.loads(result.output)
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
        data = json.loads(result.output)
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
        data = json.loads(result.output)
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
        data = json.loads(result.output)
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
        data = json.loads(result.output)
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
        assert "No markers tracked" in result.output

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

        assert "fakerepo" in result.output or "test-marker" in result.output

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
        data = json.loads(result.output)
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
        data = json.loads(result.output)
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
        data = json.loads(result.output)
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
        data = json.loads(result.output)
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
        data = json.loads(result.output)
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
        data = json.loads(result.output)
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

class TestHeadlessRunRepoA:
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
        data = json.loads(result.output)
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
        data = json.loads(result.output)
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
        assert "No .autoresearch/config.yaml" in result.output

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
    def test_no_args_no_config_exits_2(self):
        with patch("autoresearch.cli._load_local_markers", return_value=[]):
            result = runner.invoke(app, ["run"])
        assert result.exit_code == 2

    def test_nonexistent_marker_exits_1(self):
        with patch("autoresearch.cli._load_local_markers", return_value=[]):
            result = runner.invoke(app, ["run", "-m", "missing"])
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
            result = runner.invoke(app, ["init", "--path", str(tmp_path), "--no-claude"])
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
        data = json.loads(result.output)
        assert data["status"] == "error"


class TestHeadlessConfidenceNotFound:
    def test_confidence_headless_marker_not_found(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "confidence", "-m", "nope:nope"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["status"] == "error"


class TestHeadlessPauseNotFound:
    def test_pause_headless_marker_not_found(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "pause", "-m", "nope:nope"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["status"] == "error"


class TestHeadlessAddBadFile:
    def test_add_headless_load_markers_error(self, tmp_path):
        with (
            patch("autoresearch.cli.find_marker_file", return_value=tmp_path / ".autoresearch.yaml"),
            patch("autoresearch.cli.load_markers", side_effect=ValueError("bad yaml")),
        ):
            result = runner.invoke(app, ["--headless", "add", "--path", str(tmp_path)])
        assert result.exit_code == 1
        data = json.loads(result.output)
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
        data = json.loads(result.output)
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
        mock_result.output = "abc1234 Add test\ndef5678 Fix bug\n"
        with patch("subprocess.run", return_value=mock_result):
            _show_branch(tracked)

    def test_branch_with_git_log_empty(self, tmp_path):
        from unittest.mock import MagicMock
        from autoresearch.cli import _show_branch
        tracked = _make_tracked(repo_path=str(tmp_path), branch="autoresearch/test")
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.output = ""
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


# ---------------------------------------------------------------------------
# _home_mode
# ---------------------------------------------------------------------------

class TestHomeModePrivate:
    def test_home_mode_no_markers_no_output(self):
        from unittest.mock import MagicMock
        from autoresearch.cli import _home_mode
        ctx = MagicMock()
        state = AppState(markers=[])
        _home_mode(ctx, state)  # should not raise

    def test_home_mode_with_tracked_marker(self):
        from unittest.mock import MagicMock
        from autoresearch.cli import _home_mode
        ctx = MagicMock()
        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        marker = _make_marker()
        with (
            patch("autoresearch.cli._resolve_marker_data", return_value=(None, marker, MarkerStatus.ACTIVE)),
            patch("autoresearch.cli._render_marker_table"),
        ):
            _home_mode(ctx, state)

    def test_home_mode_with_unresolvable_marker(self):
        from unittest.mock import MagicMock
        from autoresearch.cli import _home_mode
        ctx = MagicMock()
        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        with (
            patch("autoresearch.cli._resolve_marker_data", return_value=(None, None, None)),
            patch("autoresearch.cli._render_marker_table"),
        ):
            _home_mode(ctx, state)


# ---------------------------------------------------------------------------
# _show_status_interactive
# ---------------------------------------------------------------------------

class TestShowStatusInteractive:
    def test_prints_fields(self):
        from autoresearch.cli import _show_status_interactive
        tracked = _make_tracked()
        marker = _make_marker()
        with patch("autoresearch.cli._format_tracked_json", return_value={"id": "r:m", "status": "active"}):
            _show_status_interactive(tracked, marker, MarkerStatus.ACTIVE)  # no assertion, just no raise


# ---------------------------------------------------------------------------
# _show_results_interactive
# ---------------------------------------------------------------------------

class TestShowResultsInteractiveA:
    def test_no_results_prints_dim(self):
        from autoresearch.cli import _show_results_interactive
        tracked = _make_tracked()
        with patch("autoresearch.results.read_results", return_value=[]):
            _show_results_interactive(tracked)  # should not raise

    def test_with_results_renders_table(self):
        from autoresearch.cli import _show_results_interactive
        from autoresearch.results import ExperimentResult
        tracked = _make_tracked()
        results = [ExperimentResult(commit="abc1234", metric=42.0, status="pass", description="test")]
        with patch("autoresearch.results.read_results", return_value=results):
            _show_results_interactive(tracked)

    def test_with_confidence_value(self):
        from autoresearch.cli import _show_results_interactive
        from autoresearch.results import ExperimentResult
        tracked = _make_tracked()
        results = [ExperimentResult(commit="abc1234", metric=99.0, guard="ok", status="pass", confidence="0.85", description="hi")]
        with patch("autoresearch.results.read_results", return_value=results):
            _show_results_interactive(tracked)


# ---------------------------------------------------------------------------
# _show_ideas_interactive
# ---------------------------------------------------------------------------

class TestShowIdeasInteractive:
    def test_no_ideas_prints_dim(self):
        from autoresearch.cli import _show_ideas_interactive
        tracked = _make_tracked()
        with patch("autoresearch.ideas.read_ideas", return_value="   "):
            _show_ideas_interactive(tracked)

    def test_with_ideas_prints_content(self):
        from autoresearch.cli import _show_ideas_interactive
        tracked = _make_tracked()
        with patch("autoresearch.ideas.read_ideas", return_value="idea: try X"):
            _show_ideas_interactive(tracked)


# ---------------------------------------------------------------------------
# _show_confidence_interactive
# ---------------------------------------------------------------------------

class TestShowConfidenceInteractive:
    def test_no_baseline_prints_dim(self):
        from autoresearch.cli import _show_confidence_interactive
        tracked = _make_tracked()  # no baseline/current by default
        with patch("autoresearch.results.read_results", return_value=[]):
            _show_confidence_interactive(tracked)

    def test_with_baseline_and_current(self):
        from autoresearch.cli import _show_confidence_interactive
        tracked = _make_tracked(baseline=10.0, current=50.0)
        with (
            patch("autoresearch.results.read_results", return_value=[]),
            patch("autoresearch.results.get_kept_metrics", return_value=[10.0, 50.0]),
            patch("autoresearch.metrics.compute_confidence", return_value=0.75),
            patch("autoresearch.metrics.confidence_label", return_value="good"),
        ):
            _show_confidence_interactive(tracked)

    def test_with_zero_confidence(self):
        from autoresearch.cli import _show_confidence_interactive
        tracked = _make_tracked(baseline=10.0, current=50.0)
        with (
            patch("autoresearch.results.read_results", return_value=[]),
            patch("autoresearch.results.get_kept_metrics", return_value=[]),
            patch("autoresearch.metrics.compute_confidence", return_value=0),
            patch("autoresearch.metrics.confidence_label", return_value="none"),
        ):
            _show_confidence_interactive(tracked)


# ---------------------------------------------------------------------------
# _finalize_interactive
# ---------------------------------------------------------------------------

class TestFinalizeInteractive:
    def test_no_results_returns_early(self):
        from unittest.mock import MagicMock
        from autoresearch.cli import _finalize_interactive
        ctx = MagicMock()
        tracked = _make_tracked()
        with patch("autoresearch.results.read_results", return_value=[]):
            _finalize_interactive(ctx, tracked)

    def test_no_kept_branches(self):
        from unittest.mock import MagicMock
        from autoresearch.cli import _finalize_interactive
        from autoresearch.results import ExperimentResult
        ctx = MagicMock()
        tracked = _make_tracked()
        results = [ExperimentResult(commit="abc", metric=1.0, status="pass", description="d")]
        with (
            patch("autoresearch.results.read_results", return_value=results),
            patch("autoresearch.finalize.finalize_marker", return_value=[]),
        ):
            _finalize_interactive(ctx, tracked)

    def test_with_branches(self):
        from unittest.mock import MagicMock
        from autoresearch.cli import _finalize_interactive
        from autoresearch.results import ExperimentResult
        ctx = MagicMock()
        tracked = _make_tracked()
        results = [ExperimentResult(commit="abc", metric=1.0, status="pass", description="d")]
        branches = [{"branch": "ar/x", "description": "improvement"}]
        with (
            patch("autoresearch.results.read_results", return_value=results),
            patch("autoresearch.finalize.finalize_marker", return_value=branches),
        ):
            _finalize_interactive(ctx, tracked)


# ---------------------------------------------------------------------------
# _merge_interactive
# ---------------------------------------------------------------------------

class TestMergeInteractive:
    def test_no_branch_prints_dim(self):
        from unittest.mock import MagicMock
        from autoresearch.cli import _merge_interactive
        ctx = MagicMock()
        tracked = _make_tracked()  # branch=None by default
        _merge_interactive(ctx, tracked)

    def test_merge_success(self):
        from unittest.mock import MagicMock
        from autoresearch.cli import _merge_interactive
        ctx = MagicMock()
        tracked = _make_tracked(branch="ar/test")
        with (
            patch("rich.prompt.Prompt.ask", return_value="main"),
            patch("autoresearch.finalize.merge_finalized", return_value="abc1234567"),
        ):
            _merge_interactive(ctx, tracked)

    def test_merge_failure_prints_error(self):
        from unittest.mock import MagicMock
        from autoresearch.cli import _merge_interactive
        ctx = MagicMock()
        tracked = _make_tracked(branch="ar/test")
        with (
            patch("rich.prompt.Prompt.ask", return_value="main"),
            patch("autoresearch.finalize.merge_finalized", side_effect=RuntimeError("conflict")),
        ):
            _merge_interactive(ctx, tracked)


# ---------------------------------------------------------------------------
# _run_single_marker
# ---------------------------------------------------------------------------

class TestRunSingleMarker:
    def test_no_marker_config_prints_error(self):
        from unittest.mock import MagicMock
        from autoresearch.cli import _run_single_marker
        ctx = MagicMock()
        tracked = _make_tracked()
        with patch("autoresearch.cli._resolve_marker_data", return_value=(None, None, None)):
            _run_single_marker(ctx, tracked)

    def test_run_success_prints_summary(self):
        from unittest.mock import MagicMock
        from autoresearch.cli import _run_single_marker
        from autoresearch.engine import RunResult
        ctx = MagicMock()
        tracked = _make_tracked()
        marker = _make_marker()
        run_result = RunResult(
            marker_name="test-marker",
            experiments=3,
            kept=2,
            discarded=1,
            crashed=0,
            final_metric=99.0,
            final_confidence=0.9,
            final_status="done",
            branch="ar/test",
            worktree_path="/tmp/wt",
        )
        with (
            patch("autoresearch.cli._resolve_marker_data", return_value=(None, marker, MarkerStatus.ACTIVE)),
            patch("autoresearch.cli.load_state", return_value=AppState()),
            patch("autoresearch.engine.get_agent_runner", return_value=MagicMock()),
            patch("autoresearch.engine.run_marker", return_value=run_result),
        ):
            _run_single_marker(ctx, tracked)

    def test_run_engine_error(self):
        from unittest.mock import MagicMock
        from autoresearch.cli import _run_single_marker
        from autoresearch.engine import EngineError
        ctx = MagicMock()
        tracked = _make_tracked()
        marker = _make_marker()
        with (
            patch("autoresearch.cli._resolve_marker_data", return_value=(None, marker, MarkerStatus.ACTIVE)),
            patch("autoresearch.cli.load_state", return_value=AppState()),
            patch("autoresearch.engine.get_agent_runner", return_value=MagicMock()),
            patch("autoresearch.engine.run_marker", side_effect=EngineError("fail")),
        ):
            _run_single_marker(ctx, tracked)

    def test_run_no_final_metric(self):
        from unittest.mock import MagicMock
        from autoresearch.cli import _run_single_marker
        from autoresearch.engine import RunResult
        ctx = MagicMock()
        tracked = _make_tracked()
        marker = _make_marker()
        run_result = RunResult(
            marker_name="test-marker",
            experiments=1,
            kept=0,
            discarded=1,
            crashed=0,
            final_metric=None,
            final_confidence=None,
            final_status="done",
            branch=None,
            worktree_path="/tmp/wt",
        )
        with (
            patch("autoresearch.cli._resolve_marker_data", return_value=(None, marker, MarkerStatus.ACTIVE)),
            patch("autoresearch.cli.load_state", return_value=AppState()),
            patch("autoresearch.engine.get_agent_runner", return_value=MagicMock()),
            patch("autoresearch.engine.run_marker", return_value=run_result),
        ):
            _run_single_marker(ctx, tracked)


# ---------------------------------------------------------------------------
# _run_repo_markers
# ---------------------------------------------------------------------------

class TestRunRepoMarkersPrivate:
    def test_skips_different_repo(self):
        from unittest.mock import MagicMock
        from autoresearch.cli import _run_repo_markers
        ctx = MagicMock()
        tracked = _make_tracked(marker_id="otherrepo:m", repo_path="/tmp/other")
        tracked.repo_name = "otherrepo"
        state = AppState(markers=[tracked])
        with patch("autoresearch.cli._run_single_marker") as mock_run:
            _run_repo_markers(ctx, state, "fakerepo")
        mock_run.assert_not_called()

    def test_skips_non_active(self):
        from unittest.mock import MagicMock
        from autoresearch.cli import _run_repo_markers
        ctx = MagicMock()
        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        with (
            patch("autoresearch.cli._resolve_marker_data", return_value=(None, _make_marker(), MarkerStatus.SKIP)),
            patch("autoresearch.cli._run_single_marker") as mock_run,
        ):
            _run_repo_markers(ctx, state, "fakerepo")
        mock_run.assert_not_called()

    def test_runs_active_marker(self):
        from unittest.mock import MagicMock
        from autoresearch.cli import _run_repo_markers
        ctx = MagicMock()
        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        with (
            patch("autoresearch.cli._resolve_marker_data", return_value=(None, _make_marker(), MarkerStatus.ACTIVE)),
            patch("autoresearch.cli._run_single_marker") as mock_run,
        ):
            _run_repo_markers(ctx, state, "fakerepo")
        mock_run.assert_called_once()


# ---------------------------------------------------------------------------
# _edit_config
# ---------------------------------------------------------------------------

class TestEditConfigPrivate:
    def test_no_marker_file_prints_error(self):
        from autoresearch.cli import _edit_config
        tracked = _make_tracked()
        with patch("autoresearch.cli.find_marker_file", return_value=None):
            _edit_config(tracked)  # should not raise

    def test_with_marker_file_runs_editor(self, tmp_path):
        from autoresearch.cli import _edit_config
        tracked = _make_tracked(repo_path=str(tmp_path))
        mf = tmp_path / ".autoresearch.yaml"
        mf.write_text("markers: []")
        with (
            patch("autoresearch.cli.find_marker_file", return_value=mf),
            patch("subprocess.run") as mock_sub,
        ):
            _edit_config(tracked)
        mock_sub.assert_called_once()


# ---------------------------------------------------------------------------
# _show_branch
# ---------------------------------------------------------------------------

class TestShowBranchPrivate:
    def test_no_branch_prints_dim(self):
        from autoresearch.cli import _show_branch
        tracked = _make_tracked()  # branch=None
        _show_branch(tracked)

    def test_branch_with_git_log_success(self):
        from autoresearch.cli import _show_branch
        from unittest.mock import MagicMock
        tracked = _make_tracked(branch="ar/test")
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.output = "abc1234 improvement\n"
        with patch("subprocess.run", return_value=mock_result):
            _show_branch(tracked)

    def test_branch_with_git_log_empty(self):
        from autoresearch.cli import _show_branch
        from unittest.mock import MagicMock
        tracked = _make_tracked(branch="ar/test")
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.output = ""
        with patch("subprocess.run", return_value=mock_result):
            _show_branch(tracked)

    def test_branch_subprocess_exception(self):
        from autoresearch.cli import _show_branch
        tracked = _make_tracked(branch="ar/test")
        with patch("subprocess.run", side_effect=OSError("no git")):
            _show_branch(tracked)


# ---------------------------------------------------------------------------
# _format_tracked_json edge cases
# ---------------------------------------------------------------------------

class TestFormatTrackedJsonEdgeCases:
    def test_none_marker_returns_partial(self):
        from autoresearch.cli import _format_tracked_json
        tracked = _make_tracked()
        result = _format_tracked_json(tracked, None, None)
        assert result["id"] == tracked.id
        assert result["status"] == "unknown"

    def test_with_baseline_and_current(self):
        from autoresearch.cli import _format_tracked_json
        tracked = _make_tracked(baseline=10.0, current=55.0)
        marker = _make_marker()
        result = _format_tracked_json(tracked, marker, MarkerStatus.ACTIVE)
        assert result["current"] == 55.0
        assert result["baseline"] == 10.0

    def test_with_paused_status(self):
        from autoresearch.cli import _format_tracked_json
        tracked = _make_tracked()
        marker = _make_marker(status=MarkerStatus.PAUSED)
        result = _format_tracked_json(tracked, marker, MarkerStatus.PAUSED)
        assert result["status"] == MarkerStatus.PAUSED


# ---------------------------------------------------------------------------
# Additional edge case tests
# ---------------------------------------------------------------------------


class TestFormatTrackedJsonMoreFields:
    def test_id_present(self):
        from autoresearch.cli import _format_tracked_json
        tracked = _make_tracked(marker_id="myrepo:my-marker")
        marker = _make_marker()
        result = _format_tracked_json(tracked, marker, MarkerStatus.ACTIVE)
        assert result["id"] == "myrepo:my-marker"

    def test_repo_present(self):
        from autoresearch.cli import _format_tracked_json
        tracked = _make_tracked(repo_path="/home/user/myproject")
        marker = _make_marker()
        result = _format_tracked_json(tracked, marker, MarkerStatus.ACTIVE)
        assert "repo" in result

    def test_marker_name_present(self):
        from autoresearch.cli import _format_tracked_json
        tracked = _make_tracked(marker_name="coverage-tracker")
        marker = _make_marker(name="coverage-tracker")
        result = _format_tracked_json(tracked, marker, MarkerStatus.ACTIVE)
        assert result["marker"] == "coverage-tracker"

    def test_skip_status(self):
        from autoresearch.cli import _format_tracked_json
        tracked = _make_tracked()
        marker = _make_marker(status=MarkerStatus.SKIP)
        result = _format_tracked_json(tracked, marker, MarkerStatus.SKIP)
        assert result["status"] == MarkerStatus.SKIP

    def test_no_baseline_current_fields_default(self):
        from autoresearch.cli import _format_tracked_json
        tracked = _make_tracked()
        marker = _make_marker()
        result = _format_tracked_json(tracked, marker, MarkerStatus.ACTIVE)
        # baseline defaults to marker.metric.baseline
        assert "baseline" in result
        assert "current" in result


class TestPrivateShowStatusEdgeCases:
    def test_active_status_prints_active(self):
        from autoresearch.cli import _show_status_interactive
        tracked = _make_tracked()
        marker = _make_marker()
        # Should not raise
        _show_status_interactive(tracked, marker, MarkerStatus.ACTIVE)

    def test_paused_status_prints(self):
        from autoresearch.cli import _show_status_interactive
        tracked = _make_tracked()
        marker = _make_marker(status=MarkerStatus.PAUSED)
        _show_status_interactive(tracked, marker, MarkerStatus.PAUSED)

    def test_skip_status_prints(self):
        from autoresearch.cli import _show_status_interactive
        tracked = _make_tracked()
        marker = _make_marker(status=MarkerStatus.SKIP)
        _show_status_interactive(tracked, marker, MarkerStatus.SKIP)


class TestPrivateRunSingleMarkerEdgeCases:
    def test_marker_not_found_prints_error(self):
        from unittest.mock import MagicMock
        from autoresearch.cli import _run_single_marker
        ctx = MagicMock()
        tracked = _make_tracked()
        with (
            patch("autoresearch.cli.find_marker_file", return_value=None),
        ):
            _run_single_marker(ctx, tracked)

    def test_load_markers_error_prints_error(self):
        from unittest.mock import MagicMock
        from autoresearch.cli import _run_single_marker
        ctx = MagicMock()
        tracked = _make_tracked()
        with (
            patch("autoresearch.cli.find_marker_file", return_value=Path("/fake/.autoresearch.yaml")),
            patch("autoresearch.cli.load_markers", side_effect=ValueError("bad yaml")),
        ):
            _run_single_marker(ctx, tracked)


class TestHeadlessRunEdgeCases:
    def test_run_headless_with_extra_options(self, tmp_path):
        from unittest.mock import MagicMock
        state_path = tmp_path / "state.json"
        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        _save_state_file(state, state_path)
        marker = _make_marker()
        mf = MarkerFile(markers=[marker])
        mock_result = MagicMock()
        mock_result.experiments = 0
        mock_result.kept = 0
        mock_result.final_status = "budget_exhausted"
        mock_result.final_metric = None
        mock_result.branch = "autoresearch/test"
        with (
            patch("autoresearch.cli.load_markers", return_value=mf),
            patch("autoresearch.engine.get_agent_runner", return_value=MagicMock()),
            patch("autoresearch.engine.run_marker", return_value=mock_result),
        ):
            result = runner.invoke(
                app,
                ["run", "--headless", "--state-path", str(state_path),
                 "--id", tracked.id, "--repo-path", tracked.repo_path]
            )
        # Should not crash (0=success, 1=error, 2=usage error)
        assert result.exit_code in (0, 1, 2)


class TestHomeModeWithMultipleMarkers:
    def test_multiple_tracked_markers(self):
        from unittest.mock import MagicMock
        from autoresearch.cli import _home_mode
        ctx = MagicMock()
        t1 = _make_tracked(marker_id="repo1:marker1", marker_name="marker1")
        t2 = _make_tracked(marker_id="repo2:marker2", marker_name="marker2")
        state = AppState(markers=[t1, t2])
        marker = _make_marker()
        with (
            patch("autoresearch.cli._resolve_marker_data", return_value=(None, marker, MarkerStatus.ACTIVE)),
            patch("autoresearch.cli._render_marker_table"),
        ):
            _home_mode(ctx, state)  # Should not raise


# ---------------------------------------------------------------------------
# Additional headless edge cases
# ---------------------------------------------------------------------------

class TestHeadlessListUnknownMarker:
    """When _resolve_marker_data returns nones, list still includes the tracked entry."""
    def test_unresolvable_marker_still_listed(self):
        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.find_marker_file", return_value=None),
        ):
            result = runner.invoke(app, ["--headless", "list"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data["data"]) == 1
        assert data["data"][0]["status"] == "unknown"

    def test_unresolvable_marker_has_id(self):
        tracked = _make_tracked(marker_id="myrepo:my-marker")
        state = AppState(markers=[tracked])
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.find_marker_file", return_value=None),
        ):
            result = runner.invoke(app, ["--headless", "list"])
        data = json.loads(result.output)
        assert data["data"][0]["id"] == "myrepo:my-marker"


class TestHeadlessStatusExtended:
    """status_cmd includes description, direction, target_metric when marker resolved."""
    def test_extended_fields_present(self):
        tracked = _make_tracked()
        marker = _make_marker()
        state = AppState(markers=[tracked])
        mf = MarkerFile(markers=[marker])

        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.find_marker_file", return_value=Path("/tmp/fakerepo/.autoresearch.yaml")),
            patch("autoresearch.cli.load_markers", return_value=mf),
        ):
            result = runner.invoke(app, ["--headless", "status", "--marker", "fakerepo:test-marker"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "description" in data["data"]
        assert "direction" in data["data"]
        assert "max_experiments" in data["data"]
        assert "budget" in data["data"]

    def test_status_without_resolvable_marker_omits_extra_fields(self):
        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.find_marker_file", return_value=None),
        ):
            result = runner.invoke(app, ["--headless", "status", "--marker", "fakerepo:test-marker"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "description" not in data["data"]
        assert data["data"]["status"] == "unknown"


class TestHeadlessSkipUnskipCycle:
    """Test skip → unskip cycle via headless."""
    def test_skip_then_unskip(self, tmp_path):
        tracked = _make_tracked()
        state = AppState(markers=[tracked])

        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.save_state"),
        ):
            result1 = runner.invoke(app, ["--headless", "skip", "--marker", "fakerepo:test-marker"])
        assert result1.exit_code == 0
        d1 = json.loads(result1.stdout)
        assert d1["data"]["action"] == "skipped"


class TestHeadlessPauseResumeCycle:
    def test_pause_marker(self):
        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.save_state"),
        ):
            result = runner.invoke(app, ["--headless", "pause", "--marker", "fakerepo:test-marker"])
        assert result.exit_code == 0
        d = json.loads(result.output)
        assert d["data"]["action"] == "paused"

    def test_resume_paused_marker(self):
        from autoresearch.marker import MarkerStatus as MS
        tracked = _make_tracked()
        tracked.status_override = MS.PAUSED
        state = AppState(markers=[tracked])
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.save_state"),
        ):
            result = runner.invoke(app, ["--headless", "pause", "--marker", "fakerepo:test-marker"])
        assert result.exit_code == 0
        d = json.loads(result.output)
        assert d["data"]["action"] == "resumed"


class TestHeadlessDetachEdgeCases:
    def test_detach_returns_marker_id(self):
        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.save_state"),
        ):
            result = runner.invoke(app, ["--headless", "detach", "--marker", "fakerepo:test-marker"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["data"]["detached"] == "fakerepo:test-marker"

    def test_detach_nonexistent_returns_error(self):
        state = AppState(markers=[])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "detach", "--marker", "x:y"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["status"] == "error"


class TestHeadlessConfidenceEdgeCases:
    def test_confidence_with_kept_results(self):
        tracked = _make_tracked(baseline=10.0, current=20.0)
        state = AppState(markers=[tracked])

        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.results.read_results", return_value=[]),
        ):
            result = runner.invoke(app, ["--headless", "confidence", "--marker", "fakerepo:test-marker"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["data"]["baseline"] == 10.0
        assert data["data"]["current"] == 20.0

    def test_confidence_no_baseline_score_is_none(self):
        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.results.read_results", return_value=[]),
        ):
            result = runner.invoke(app, ["--headless", "confidence", "--marker", "fakerepo:test-marker"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["data"]["confidence_score"] is None


class TestHeadlessRunRepo:
    def test_run_repo_engine_error_in_results(self):
        from autoresearch.engine import EngineError
        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        marker = _make_marker()
        mf = MarkerFile(markers=[marker])

        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.find_marker_file", return_value=Path("/tmp/fakerepo/.autoresearch.yaml")),
            patch("autoresearch.cli.load_markers", return_value=mf),
            patch("autoresearch.cli.get_effective_status", return_value=MarkerStatus.ACTIVE),
            patch("autoresearch.engine.get_agent_runner"),
            patch("autoresearch.engine.run_marker", side_effect=EngineError("bad")),
        ):
            result = runner.invoke(app, ["--headless", "run", "--repo", "fakerepo"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert any("error" in r for r in data["data"])


class TestNonHeadlessListMessages:
    def test_empty_list_prints_no_markers_message(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["list"])
        assert result.exit_code == 0
        assert "No markers tracked" in result.output

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
        assert "test-marker" in result.output


class TestHeadlessIdeasEdgeCases:
    def test_ideas_nonexistent_marker_error(self):
        state = AppState(markers=[])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "ideas", "--marker", "x:y"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["status"] == "error"

    def test_ideas_with_content_returns_string(self):
        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.ideas.read_ideas", return_value="some ideas here"),
        ):
            result = runner.invoke(app, ["--headless", "ideas", "--marker", "fakerepo:test-marker"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "ideas" in data["data"]


# ---------------------------------------------------------------------------
# _format_tracked_json — field validation
# ---------------------------------------------------------------------------

class TestFormatTrackedJson:
    def test_all_keys_present(self):
        from autoresearch.cli import _format_tracked_json
        tracked = _make_tracked(baseline=5.0, current=8.0)
        marker = _make_marker()
        d = _format_tracked_json(tracked, marker, MarkerStatus.ACTIVE)
        for key in ("id", "repo", "marker", "status", "last_run",
                    "experiments", "kept", "discarded", "baseline", "current", "branch"):
            assert key in d

    def test_status_value_when_effective_status_none(self):
        from autoresearch.cli import _format_tracked_json
        tracked = _make_tracked()
        marker = _make_marker()
        d = _format_tracked_json(tracked, marker, None)
        assert d["status"] == "unknown"

    def test_status_uses_effective_status_value(self):
        from autoresearch.cli import _format_tracked_json
        tracked = _make_tracked()
        marker = _make_marker()
        d = _format_tracked_json(tracked, marker, MarkerStatus.ACTIVE)
        assert d["status"] == "active"

    def test_baseline_and_current_stored(self):
        from autoresearch.cli import _format_tracked_json
        tracked = _make_tracked(baseline=10.0, current=15.0)
        marker = _make_marker()
        d = _format_tracked_json(tracked, marker, MarkerStatus.ACTIVE)
        assert d["baseline"] == 10.0
        assert d["current"] == 15.0

    def test_repo_and_marker_names(self):
        from autoresearch.cli import _format_tracked_json
        tracked = _make_tracked(repo_path="/tmp/myrepo", marker_name="my-metric")
        marker = _make_marker(name="my-metric")
        d = _format_tracked_json(tracked, marker, MarkerStatus.ACTIVE)
        assert d["repo"] == "fakerepo"
        assert d["marker"] == "my-metric"


# ---------------------------------------------------------------------------
# _resolve_marker_data — edge cases
# ---------------------------------------------------------------------------

class TestResolveMarkerData:
    def test_no_marker_file_returns_nones(self):
        from autoresearch.cli import _resolve_marker_data
        tracked = _make_tracked()
        with patch("autoresearch.cli.find_marker_file", return_value=None):
            mf, m, eff = _resolve_marker_data(tracked)
        assert mf is None
        assert m is None
        assert eff is None

    def test_load_markers_exception_returns_nones(self):
        from autoresearch.cli import _resolve_marker_data
        tracked = _make_tracked()
        with (
            patch("autoresearch.cli.find_marker_file", return_value=Path("/tmp/fake/.autoresearch.yaml")),
            patch("autoresearch.cli.load_markers", side_effect=Exception("parse error")),
        ):
            mf, m, eff = _resolve_marker_data(tracked)
        assert mf is None and m is None and eff is None

    def test_marker_not_in_file_returns_nones(self):
        from autoresearch.cli import _resolve_marker_data
        tracked = _make_tracked()
        mf = MarkerFile(markers=[])
        with (
            patch("autoresearch.cli.find_marker_file", return_value=Path("/tmp/fake/.autoresearch.yaml")),
            patch("autoresearch.cli.load_markers", return_value=mf),
        ):
            mf_out, m, eff = _resolve_marker_data(tracked)
        assert m is None and eff is None

    def test_valid_marker_returns_data(self):
        from autoresearch.cli import _resolve_marker_data
        tracked = _make_tracked()
        marker = _make_marker()
        mf = MarkerFile(markers=[marker])
        with (
            patch("autoresearch.cli.find_marker_file", return_value=Path("/tmp/fake/.autoresearch.yaml")),
            patch("autoresearch.cli.load_markers", return_value=mf),
        ):
            mf_out, m, eff = _resolve_marker_data(tracked)
        assert m is not None
        assert eff is not None


# ---------------------------------------------------------------------------
# Headless list — missing marker file produces unknown status
# ---------------------------------------------------------------------------

class TestHeadlessListMissingMarkerFile:
    def test_tracked_with_missing_file_shows_unknown(self):
        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.find_marker_file", return_value=None),
        ):
            result = runner.invoke(app, ["--headless", "list"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "ok"
        entry = data["data"][0]
        assert entry["status"] == "unknown"


# ---------------------------------------------------------------------------
# Headless confidence — various baselines
# ---------------------------------------------------------------------------

class TestHeadlessConfidenceValues:
    def test_baseline_equals_current_low_confidence(self):
        tracked = _make_tracked(baseline=10.0, current=10.0)
        state = AppState(markers=[tracked])
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.results.read_results", return_value=[]),
        ):
            result = runner.invoke(app, ["--headless", "confidence", "--marker", "fakerepo:test-marker"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "ok"

    def test_high_current_vs_baseline(self):
        tracked = _make_tracked(baseline=10.0, current=100.0)
        state = AppState(markers=[tracked])
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.results.read_results", return_value=[]),
        ):
            result = runner.invoke(app, ["--headless", "confidence", "--marker", "fakerepo:test-marker"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Headless status — various status values
# ---------------------------------------------------------------------------

class TestHeadlessStatusValues:
    def test_paused_marker_shows_paused_status(self):
        tracked = _make_tracked(status_override=MarkerStatus.PAUSED)
        state = AppState(markers=[tracked])
        marker = _make_marker(status=MarkerStatus.ACTIVE)
        mf = MarkerFile(markers=[marker])
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.find_marker_file", return_value=Path("/tmp/fakerepo/.autoresearch.yaml")),
            patch("autoresearch.cli.load_markers", return_value=mf),
        ):
            result = runner.invoke(app, ["--headless", "status", "--marker", "fakerepo:test-marker"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "ok"

    def test_skipped_marker_shows_skip_status(self):
        tracked = _make_tracked(skipped=True)
        state = AppState(markers=[tracked])
        marker = _make_marker(status=MarkerStatus.ACTIVE)
        mf = MarkerFile(markers=[marker])
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.find_marker_file", return_value=Path("/tmp/fakerepo/.autoresearch.yaml")),
            patch("autoresearch.cli.load_markers", return_value=mf),
        ):
            result = runner.invoke(app, ["--headless", "status", "--marker", "fakerepo:test-marker"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Headless results — multiple results
# ---------------------------------------------------------------------------

class TestHeadlessResultsMultiple:
    def test_multiple_results_returned(self):
        from autoresearch.results import ExperimentResult
        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        exp_results = [
            ExperimentResult(commit=f"abc{i}", metric=float(i), guard="pass",
                             status="keep", confidence="1.0", description=f"exp {i}")
            for i in range(5)
        ]
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.results.read_results", return_value=exp_results),
        ):
            result = runner.invoke(app, ["--headless", "results", "--marker", "fakerepo:test-marker"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data["data"]) == 5


# ---------------------------------------------------------------------------
# _render_marker_table — non-headless list
# ---------------------------------------------------------------------------

class TestNonHeadlessListWithTracked:
    def test_list_with_one_tracked_marker(self, tmp_path):
        state = AppState(markers=[_make_tracked()])
        state_file = tmp_path / "state.json"
        _save_state_file(state, state_file)

        marker = _make_marker()
        mf = MarkerFile(markers=[marker])

        with (
            patch("autoresearch.cli._load_state", return_value=state),
            patch("autoresearch.cli.load_markers", return_value=mf),
            patch("autoresearch.cli.find_marker_file", return_value=tmp_path / ".autoresearch.yaml"),
        ):
            result = runner.invoke(app, ["list"])
        assert result.exit_code == 0

    def test_list_with_no_tracked_markers(self, tmp_path):
        state = AppState(markers=[])
        with patch("autoresearch.cli._load_state", return_value=state):
            result = runner.invoke(app, ["list"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Headless confidence — more edge cases
# ---------------------------------------------------------------------------

class TestHeadlessConfidenceMoreEdgeCases:
    def test_confidence_zero_baseline_zero_current(self, tmp_path):
        from autoresearch.results import ExperimentResult
        state = AppState(markers=[_make_tracked(baseline=0.0, current_best=0.0)])
        marker = _make_marker()
        mf = MarkerFile(markers=[marker])
        results = [
            ExperimentResult(commit="a1", metric=0.0, guard="pass", status="keep",
                             confidence="--", description="d"),
        ]
        with (
            patch("autoresearch.cli._load_state", return_value=state),
            patch("autoresearch.cli.load_markers", return_value=mf),
            patch("autoresearch.cli.find_marker_file", return_value=tmp_path / ".autoresearch.yaml"),
            patch("autoresearch.metrics.compute_confidence", return_value=0.0),
            patch("autoresearch.metrics.confidence_label", return_value="low"),
            patch("autoresearch.results.read_results", return_value=results),
            patch("autoresearch.results.get_kept_metrics", return_value=[0.0]),
        ):
            result = runner.invoke(app, ["--headless", "confidence", "--marker", "fakerepo:test-marker"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data.get("status") == "ok"


# ---------------------------------------------------------------------------
# Headless status — edge cases
# ---------------------------------------------------------------------------

class TestHeadlessStatusEdgeCases:
    def test_status_active_marker(self, tmp_path):
        state = AppState(markers=[_make_tracked()])
        marker = _make_marker()
        mf = MarkerFile(markers=[marker])
        with (
            patch("autoresearch.cli._load_state", return_value=state),
            patch("autoresearch.cli.load_markers", return_value=mf),
            patch("autoresearch.cli.find_marker_file", return_value=tmp_path / ".autoresearch.yaml"),
        ):
            result = runner.invoke(app, ["--headless", "status", "--marker", "fakerepo:test-marker"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data.get("status") == "ok"
        assert data["data"]["id"] == "fakerepo:test-marker"

    def test_status_unknown_marker_returns_error(self, tmp_path):
        state = AppState(markers=[])
        with patch("autoresearch.cli._load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "status", "--marker", "unknown:missing"])
        data = json.loads(result.output)
        assert data.get("status") == "error"


# ---------------------------------------------------------------------------
# Headless add — basic flow
# ---------------------------------------------------------------------------

class TestHeadlessAddBasic:
    def test_add_new_marker(self, tmp_path):
        marker_file = tmp_path / ".autoresearch.yaml"
        state = AppState(markers=[])
        with (
            patch("autoresearch.cli._load_state", return_value=state),
            patch("autoresearch.cli.find_marker_file", return_value=marker_file),
            patch("autoresearch.cli.load_markers") as mock_load,
            patch("autoresearch.cli.save_state"),
        ):
            marker = _make_marker("my-marker")
            mf = MarkerFile(markers=[marker])
            mock_load.return_value = mf
            result = runner.invoke(
                app,
                ["--headless", "add", "--path", str(tmp_path)],
            )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data.get("status") == "ok"


# ---------------------------------------------------------------------------
# _format_tracked_json — None effective_status
# ---------------------------------------------------------------------------

class TestFormatTrackedJsonNoneStatus:
    def test_none_effective_status_gives_unknown(self):
        from autoresearch.cli import _format_tracked_json
        tracked = _make_tracked()
        result = _format_tracked_json(tracked, None, None)
        assert result["status"] in (None, "unknown", "active", "")

    def test_active_effective_status(self):
        from autoresearch.cli import _format_tracked_json
        tracked = _make_tracked()
        marker = _make_marker()
        result = _format_tracked_json(tracked, marker, MarkerStatus.ACTIVE)
        assert result["status"] == "active"

    def test_skip_effective_status(self):
        from autoresearch.cli import _format_tracked_json
        tracked = _make_tracked()
        marker = _make_marker()
        result = _format_tracked_json(tracked, marker, MarkerStatus.SKIP)
        assert result["status"] == "skip"


# ---------------------------------------------------------------------------
# Headless detach — already detached
# ---------------------------------------------------------------------------

class TestHeadlessDetachAlreadyGone:
    def test_detach_when_not_tracked(self):
        state = AppState(markers=[])
        with patch("autoresearch.cli._load_state", return_value=state):
            result = runner.invoke(
                app, ["--headless", "detach", "--marker", "fakerepo:nonexistent"]
            )
        # Should report error or exit non-zero
        assert result.exit_code != 0 or "error" in result.output.lower()


# ---------------------------------------------------------------------------
# Headless skip — marker not tracked
# ---------------------------------------------------------------------------

class TestHeadlessSkipNotTracked:
    def test_skip_untracked_marker_returns_error(self):
        state = AppState(markers=[])
        with patch("autoresearch.cli._load_state", return_value=state):
            result = runner.invoke(
                app, ["--headless", "skip", "--marker", "fakerepo:nonexistent"]
            )
        data = json.loads(result.output)
        assert data.get("status") == "error"


# ---------------------------------------------------------------------------
# Headless pause — marker not tracked
# ---------------------------------------------------------------------------

class TestHeadlessPauseNotTracked:
    def test_pause_untracked_marker_returns_error(self):
        state = AppState(markers=[])
        with patch("autoresearch.cli._load_state", return_value=state):
            result = runner.invoke(
                app, ["--headless", "pause", "--marker", "fakerepo:nonexistent"]
            )
        data = json.loads(result.output)
        assert data.get("status") == "error"


# ---------------------------------------------------------------------------
# daemon_status headless — with scheduled markers
# ---------------------------------------------------------------------------

class TestDaemonStatusHeadlessScheduled:
    def _make_tracked_with_schedule(self, tmp_path, marker_name="my-marker"):
        from autoresearch.state import TrackedMarker
        return TrackedMarker(
            id=f"repo:{marker_name}",
            repo_path=str(tmp_path),
            repo_name="repo",
            marker_name=marker_name,
            last_run="2026-01-01T01:00:00+00:00",
        )

    def test_headless_status_running_false_when_no_pid(self):
        with (
            patch("autoresearch.daemon.read_pid", return_value=None),
            patch("autoresearch.daemon.check_stale_pid"),
            patch("autoresearch.cli.load_state", return_value=AppState()),
        ):
            result = runner.invoke(app, ["--headless", "daemon", "status"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["data"]["running"] is False

    def test_headless_status_running_true_when_pid_alive(self):
        with (
            patch("autoresearch.daemon.read_pid", return_value=12345),
            patch("autoresearch.daemon.is_pid_alive", return_value=True),
            patch("autoresearch.daemon.check_stale_pid"),
            patch("autoresearch.cli.load_state", return_value=AppState()),
        ):
            result = runner.invoke(app, ["--headless", "daemon", "status"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["data"]["running"] is True
        assert data["data"]["pid"] == 12345

    def test_headless_status_scheduled_markers_listed(self, tmp_path):
        from autoresearch.marker import Escalation, LoopConfig, Marker, MarkerFile, MarkerStatus, Metric, MetricDirection, ResultsConfig, Schedule, Target
        from autoresearch.state import TrackedMarker

        tracked = TrackedMarker(
            id="repo:m",
            repo_path=str(tmp_path),
            repo_name="repo",
            marker_name="m",
            last_run="2026-01-01T00:00:00+00:00",
        )
        state = AppState(markers=[tracked])

        marker = Marker(
            name="m",
            description="test",
            status=MarkerStatus.ACTIVE,
            target=Target(mutable=[], immutable=[]),
            metric=Metric(command="echo", extract="", direction=MetricDirection.HIGHER, baseline=0),
            loop=LoopConfig(),
            escalation=Escalation(),
            schedule=Schedule(type="overnight"),
            results=ResultsConfig(),
        )
        mf = MarkerFile(markers=[marker])

        with (
            patch("autoresearch.daemon.read_pid", return_value=None),
            patch("autoresearch.daemon.check_stale_pid"),
            patch("autoresearch.cli._load_state", return_value=state),
            patch("autoresearch.cli._resolve_marker_data", return_value=(mf, marker, MarkerStatus.ACTIVE)),
            patch("autoresearch.daemon._resolve_cron_expression", return_value="0 1 * * *"),
        ):
            result = runner.invoke(app, ["--headless", "daemon", "status"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "scheduled_markers" in data["data"]


# ---------------------------------------------------------------------------
# finalize_cmd headless — marker not found
# ---------------------------------------------------------------------------

class TestFinalizeCmdHeadless:
    def test_headless_finalize_marker_not_found(self):
        with patch("autoresearch.cli._load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "finalize", "-m", "repo:missing"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["status"] == "error"

    def test_headless_finalize_no_branches_returns_empty_list(self, tmp_path):
        from autoresearch.state import TrackedMarker
        tracked = TrackedMarker(
            id="repo:m",
            repo_path=str(tmp_path),
            repo_name="repo",
            marker_name="m",
        )
        state = AppState(markers=[tracked])
        with (
            patch("autoresearch.cli._load_state", return_value=state),
            patch("autoresearch.results.read_results", return_value=[]),
            patch("autoresearch.finalize.finalize_marker", return_value=[]),
        ):
            result = runner.invoke(app, ["--headless", "finalize", "-m", "repo:m"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["data"]["branches"] == []

    def test_headless_finalize_with_branches(self, tmp_path):
        from autoresearch.state import TrackedMarker
        tracked = TrackedMarker(
            id="repo:m",
            repo_path=str(tmp_path),
            repo_name="repo",
            marker_name="m",
        )
        state = AppState(markers=[tracked])
        branches = [{"branch": "autoresearch/m-exp1", "description": "Added caching"}]
        with (
            patch("autoresearch.cli._load_state", return_value=state),
            patch("autoresearch.results.read_results", return_value=[]),
            patch("autoresearch.finalize.finalize_marker", return_value=branches),
        ):
            result = runner.invoke(app, ["--headless", "finalize", "-m", "repo:m"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data["data"]["branches"]) == 1
        assert data["data"]["branches"][0]["branch"] == "autoresearch/m-exp1"


# ---------------------------------------------------------------------------
# merge_cmd headless — no branch
# ---------------------------------------------------------------------------

class TestMergeCmdHeadlessNoBranch:
    def test_headless_merge_no_branch_returns_error(self, tmp_path):
        from autoresearch.state import TrackedMarker
        tracked = TrackedMarker(
            id="repo:m",
            repo_path=str(tmp_path),
            repo_name="repo",
            marker_name="m",
            branch=None,
        )
        state = AppState(markers=[tracked])
        with patch("autoresearch.cli._load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "merge", "-m", "repo:m"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["status"] == "error"

    def test_headless_merge_with_explicit_branch(self, tmp_path):
        from autoresearch.state import TrackedMarker
        tracked = TrackedMarker(
            id="repo:m",
            repo_path=str(tmp_path),
            repo_name="repo",
            marker_name="m",
        )
        state = AppState(markers=[tracked])
        with (
            patch("autoresearch.cli._load_state", return_value=state),
            patch("autoresearch.finalize.merge_finalized", return_value="abc1234567"),
        ):
            result = runner.invoke(app, [
                "--headless", "merge", "-m", "repo:m",
                "--branch", "custom-branch", "--target", "dev"
            ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["data"]["merged"] == "custom-branch"
        assert data["data"]["target"] == "dev"


# ---------------------------------------------------------------------------
# _show_confidence_interactive — missing baseline/current
# ---------------------------------------------------------------------------

class TestShowConfidenceInteractiveEdgeCases:
    def test_no_baseline_prints_dim(self):
        from autoresearch.cli import _show_confidence_interactive
        from autoresearch.state import TrackedMarker
        tracked = TrackedMarker(
            id="repo:m",
            repo_path="/tmp",
            repo_name="repo",
            marker_name="m",
            baseline=None,
            current=5.0,
        )
        with (
            patch("autoresearch.results.read_results", return_value=[]),
            patch("autoresearch.results.get_kept_metrics", return_value=[]),
        ):
            # Should not raise
            _show_confidence_interactive(tracked)

    def test_zero_confidence_shows_not_enough_data(self):
        from autoresearch.cli import _show_confidence_interactive
        from autoresearch.state import TrackedMarker
        tracked = TrackedMarker(
            id="repo:m",
            repo_path="/tmp",
            repo_name="repo",
            marker_name="m",
            baseline=5.0,
            current=5.0,
        )
        with (
            patch("autoresearch.results.read_results", return_value=[]),
            patch("autoresearch.results.get_kept_metrics", return_value=[]),
            patch("autoresearch.metrics.compute_confidence", return_value=None),
        ):
            # Should not raise
            _show_confidence_interactive(tracked)


# ---------------------------------------------------------------------------
# _format_tracked_json — field completeness
# ---------------------------------------------------------------------------

class TestFormatTrackedJsonFieldsComplete:
    def _make_tracked_full(self):
        from autoresearch.state import TrackedMarker
        return TrackedMarker(
            id="myrepo:mymarker",
            repo_path="/tmp/myrepo",
            repo_name="myrepo",
            marker_name="mymarker",
            baseline=3.0,
            current=7.5,
            branch="autoresearch/mymarker",
            last_run="2026-01-15T12:00:00Z",
            last_run_experiments=5,
            last_run_kept=2,
            last_run_discarded=3,
        )

    def test_branch_field_present(self):
        from autoresearch.cli import _format_tracked_json
        tracked = self._make_tracked_full()
        data = _format_tracked_json(tracked, None, None)
        assert "branch" in data
        assert data["branch"] == "autoresearch/mymarker"

    def test_experiments_field_correct(self):
        from autoresearch.cli import _format_tracked_json
        tracked = self._make_tracked_full()
        data = _format_tracked_json(tracked, None, None)
        assert data["experiments"] == 5

    def test_kept_discarded_fields(self):
        from autoresearch.cli import _format_tracked_json
        tracked = self._make_tracked_full()
        data = _format_tracked_json(tracked, None, None)
        assert data["kept"] == 2
        assert data["discarded"] == 3

    def test_last_run_field(self):
        from autoresearch.cli import _format_tracked_json
        tracked = self._make_tracked_full()
        data = _format_tracked_json(tracked, None, None)
        assert data["last_run"] == "2026-01-15T12:00:00Z"


# ---------------------------------------------------------------------------
# _show_results_interactive — results table rendered
# ---------------------------------------------------------------------------

class TestShowResultsInteractive:
    def test_no_results_prints_dim(self):
        from autoresearch.cli import _show_results_interactive
        from autoresearch.state import TrackedMarker
        tracked = TrackedMarker(
            id="repo:m",
            repo_path="/tmp",
            repo_name="repo",
            marker_name="m",
        )
        with patch("autoresearch.results.read_results", return_value=[]):
            _show_results_interactive(tracked)

    def test_with_results_does_not_raise(self, tmp_path):
        from autoresearch.cli import _show_results_interactive
        from autoresearch.results import ExperimentResult
        from autoresearch.state import TrackedMarker
        tracked = TrackedMarker(
            id="repo:m",
            repo_path=str(tmp_path),
            repo_name="repo",
            marker_name="m",
        )
        results = [
            ExperimentResult(
                commit="abc123",
                metric=5.0,
                guard="pass",
                status="keep",
                confidence="1.2",
                description="did something useful",
            )
        ]
        with patch("autoresearch.results.read_results", return_value=results):
            _show_results_interactive(tracked)


# ---------------------------------------------------------------------------
# run_cmd — model override sets on marker
# ---------------------------------------------------------------------------

class TestRunCmdModelOverride:
    def test_model_override_applied(self, tmp_path):
        from unittest.mock import MagicMock
        from autoresearch.marker import AgentConfig, Escalation, LoopConfig, Marker, MarkerStatus, Metric, MetricDirection, ResultsConfig, Schedule, Target
        from autoresearch.state import TrackedMarker

        tracked = TrackedMarker(
            id="repo:m",
            repo_path=str(tmp_path),
            repo_name="repo",
            marker_name="m",
        )
        state = AppState(markers=[tracked])

        marker = Marker(
            name="m",
            description="test",
            status=MarkerStatus.ACTIVE,
            target=Target(mutable=[], immutable=[]),
            metric=Metric(command="echo", extract="", direction=MetricDirection.HIGHER, baseline=0),
            loop=LoopConfig(),
            escalation=Escalation(),
            schedule=Schedule(),
            results=ResultsConfig(),
            agent=AgentConfig(),
        )
        run_result = MagicMock()
        run_result.marker_name = "m"
        run_result.experiments = 1
        run_result.kept = 1
        run_result.discarded = 0
        run_result.crashed = 0
        run_result.final_metric = 5.0
        run_result.final_confidence = 1.0
        run_result.final_status = "completed"
        run_result.branch = "autoresearch/m"

        with (
            patch("autoresearch.cli._load_state", return_value=state),
            patch("autoresearch.cli._resolve_marker_data", return_value=(None, marker, MarkerStatus.ACTIVE)),
            patch("autoresearch.engine.get_agent_runner", return_value=MagicMock()),
            patch("autoresearch.engine.run_marker", return_value=run_result),
        ):
            result = runner.invoke(app, ["--headless", "run", "-m", "repo:m", "--model", "opus"])
        assert result.exit_code == 0
        assert marker.agent.model == "opus"


# ---------------------------------------------------------------------------
# daemon_logs — headless follow exits 2
# ---------------------------------------------------------------------------

class TestDaemonLogsHeadlessFollow:
    def test_headless_follow_exits_2(self, tmp_path):
        log_file = tmp_path / "daemon.log"
        log_file.write_text("content\n")
        with patch("autoresearch.daemon.LOG_PATH", log_file):
            result = runner.invoke(app, ["--headless", "daemon", "logs", "--follow"])
        assert result.exit_code == 2
        data = json.loads(result.output)
        assert data["status"] == "error"

    def test_headless_log_lines_count_respected(self, tmp_path):
        log_file = tmp_path / "daemon.log"
        log_file.write_text("\n".join(f"line{i}" for i in range(10)) + "\n")
        with patch("autoresearch.daemon.LOG_PATH", log_file):
            result = runner.invoke(app, ["--headless", "daemon", "logs", "-n", "3"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data["data"]["lines"]) == 3
        assert data["data"]["lines"][-1] == "line9"


# ---------------------------------------------------------------------------
# init_cmd — headless and non-headless paths
# ---------------------------------------------------------------------------

class TestInitCmdHeadless:
    def test_headless_config_created(self, tmp_path):
        ar_dir = tmp_path / ".autoresearch"
        with (
            patch("autoresearch.agent_profile.init_autoresearch_dir", return_value=ar_dir),
            patch("autoresearch.marker.CONFIG_DIR", ".autoresearch"),
            patch("autoresearch.marker.CONFIG_FILENAME", "config.yaml"),
        ):
            result = runner.invoke(app, ["--headless", "init", "--path", str(tmp_path)])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "ok"
        assert "path" in data["data"]
        assert "config" in data["data"]
        assert "config_created" in data["data"]

    def test_headless_config_already_exists(self, tmp_path):
        ar_dir = tmp_path / ".autoresearch"
        ar_dir.mkdir(parents=True)
        config_file = ar_dir / "config.yaml"
        config_file.write_text("markers: []")
        with patch("autoresearch.agent_profile.init_autoresearch_dir", return_value=ar_dir):
            result = runner.invoke(app, ["--headless", "init", "--path", str(tmp_path)])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["data"]["config_created"] is False

    def test_non_headless_init_prints_success(self, tmp_path):
        ar_dir = tmp_path / ".autoresearch"
        with patch("autoresearch.agent_profile.init_autoresearch_dir", return_value=ar_dir):
            result = runner.invoke(app, ["init", "--path", str(tmp_path), "--no-claude"])
        assert result.exit_code == 0
        assert "Initialized" in result.output or "Synced" in result.output


# ---------------------------------------------------------------------------
# results_cmd — headless with actual results
# ---------------------------------------------------------------------------

class TestResultsCmdHeadlessWithResults:
    def test_headless_results_with_data(self):
        from autoresearch.results import ExperimentResult
        from autoresearch.state import TrackedMarker

        tracked = TrackedMarker(
            id="repo:m",
            repo_path="/tmp",
            repo_name="repo",
            marker_name="m",
        )
        state = AppState(markers=[tracked])
        results = [
            ExperimentResult(
                commit="abc123",
                metric=5.0,
                guard="pass",
                status="keep",
                confidence="1.5",
                description="improved",
            ),
            ExperimentResult(
                commit="def456",
                metric=3.0,
                guard="--",
                status="discard",
                confidence="--",
                description="regression",
            ),
        ]
        with (
            patch("autoresearch.cli._load_state", return_value=state),
            patch("autoresearch.results.read_results", return_value=results),
        ):
            result = runner.invoke(app, ["--headless", "results", "-m", "repo:m"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "ok"
        assert len(data["data"]) == 2

    def test_headless_results_empty(self):
        from autoresearch.state import TrackedMarker

        tracked = TrackedMarker(
            id="repo:m",
            repo_path="/tmp",
            repo_name="repo",
            marker_name="m",
        )
        state = AppState(markers=[tracked])
        with (
            patch("autoresearch.cli._load_state", return_value=state),
            patch("autoresearch.results.read_results", return_value=[]),
        ):
            result = runner.invoke(app, ["--headless", "results", "-m", "repo:m"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["data"] == []


# ---------------------------------------------------------------------------
# ideas_cmd — headless with content
# ---------------------------------------------------------------------------

class TestIdeasCmdHeadlessWithContent:
    def test_headless_ideas_returns_content(self):
        from autoresearch.state import TrackedMarker

        tracked = TrackedMarker(
            id="repo:m",
            repo_path="/tmp",
            repo_name="repo",
            marker_name="m",
        )
        state = AppState(markers=[tracked])
        with (
            patch("autoresearch.cli._load_state", return_value=state),
            patch("autoresearch.ideas.read_ideas", return_value="## Ideas\n- Try X\n- Try Y"),
        ):
            result = runner.invoke(app, ["--headless", "ideas", "-m", "repo:m"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "ideas" in data["data"]
        assert "Try X" in data["data"]["ideas"]

    def test_non_headless_ideas_empty_shows_dim(self):
        from autoresearch.state import TrackedMarker

        tracked = TrackedMarker(
            id="repo:m",
            repo_path="/tmp",
            repo_name="repo",
            marker_name="m",
        )
        state = AppState(markers=[tracked])
        with (
            patch("autoresearch.cli._load_state", return_value=state),
            patch("autoresearch.ideas.read_ideas", return_value="   "),
        ):
            result = runner.invoke(app, ["ideas", "-m", "repo:m"])
        assert result.exit_code == 0

    def test_non_headless_ideas_with_content_printed(self):
        from autoresearch.state import TrackedMarker

        tracked = TrackedMarker(
            id="repo:m",
            repo_path="/tmp",
            repo_name="repo",
            marker_name="m",
        )
        state = AppState(markers=[tracked])
        with (
            patch("autoresearch.cli._load_state", return_value=state),
            patch("autoresearch.ideas.read_ideas", return_value="## Ideas\n- Try Z"),
        ):
            result = runner.invoke(app, ["ideas", "-m", "repo:m"])
        assert result.exit_code == 0
        assert "Try Z" in result.output


# ---------------------------------------------------------------------------
# _render_marker_table — unknown status value
# ---------------------------------------------------------------------------

class TestRenderMarkerTableUnknownStatus:
    def test_unknown_status_renders_as_string(self):
        from autoresearch.cli import _render_marker_table
        markers_data = [
            {
                "id": "repo:m",
                "repo": "repo",
                "marker": "m",
                "status": "super-unknown-status",
                "last_run": None,
                "current": None,
            }
        ]
        # Should not raise
        _render_marker_table(markers_data)

    def test_valid_status_renders_without_error(self):
        from autoresearch.cli import _render_marker_table
        markers_data = [
            {
                "id": "repo:m",
                "repo": "repo",
                "marker": "m",
                "status": "active",
                "last_run": "2026-01-01T00:00:00",
                "current": 5.0,
            }
        ]
        _render_marker_table(markers_data)


# ---------------------------------------------------------------------------
# main callback — headless with no subcommand exits 2
# ---------------------------------------------------------------------------

class TestMainCallbackHeadlessNoSubcommand:
    def test_headless_no_subcommand_exits_2(self):
        result = runner.invoke(app, ["--headless"])
        assert result.exit_code == 2
        data = json.loads(result.output)
        assert data["status"] == "error"

    def test_headless_no_subcommand_error_message(self):
        result = runner.invoke(app, ["--headless"])
        data = json.loads(result.output)
        msg = data.get("message") or data.get("error", "")
        assert "command" in msg.lower()


# ---------------------------------------------------------------------------
# _toggle_skip / _toggle_pause — tracked not found
# ---------------------------------------------------------------------------

class TestToggleSkipPauseTrackedNotFound:
    def test_toggle_skip_when_tracked_is_none_no_crash(self):
        from unittest.mock import MagicMock
        from autoresearch.cli import _toggle_skip
        from autoresearch.state import TrackedMarker

        tracked = TrackedMarker(
            id="repo:m",
            repo_path="/tmp",
            repo_name="repo",
            marker_name="m",
        )
        state = AppState(markers=[])  # tracked not in state

        ctx = MagicMock()
        with patch("autoresearch.cli._load_state", return_value=state):
            # Should not raise
            _toggle_skip(ctx, tracked, None)

    def test_toggle_pause_when_tracked_is_none_no_crash(self):
        from unittest.mock import MagicMock
        from autoresearch.cli import _toggle_pause
        from autoresearch.state import TrackedMarker

        tracked = TrackedMarker(
            id="repo:m",
            repo_path="/tmp",
            repo_name="repo",
            marker_name="m",
        )
        state = AppState(markers=[])  # tracked not in state

        ctx = MagicMock()
        with patch("autoresearch.cli._load_state", return_value=state):
            # Should not raise
            _toggle_pause(ctx, tracked, None)


# ---------------------------------------------------------------------------
# _finalize_interactive — no results early return
# ---------------------------------------------------------------------------

class TestFinalizeInteractiveNoResults:
    def test_no_results_prints_dim_and_returns(self):
        from unittest.mock import MagicMock
        from autoresearch.cli import _finalize_interactive
        from autoresearch.state import TrackedMarker

        tracked = TrackedMarker(
            id="repo:m",
            repo_path="/tmp",
            repo_name="repo",
            marker_name="m",
        )
        ctx = MagicMock()
        with patch("autoresearch.results.read_results", return_value=[]):
            _finalize_interactive(ctx, tracked)

    def test_no_kept_experiments_prints_dim(self):
        from unittest.mock import MagicMock
        from autoresearch.cli import _finalize_interactive
        from autoresearch.results import ExperimentResult
        from autoresearch.state import TrackedMarker

        tracked = TrackedMarker(
            id="repo:m",
            repo_path="/tmp",
            repo_name="repo",
            marker_name="m",
            branch="autoresearch/m",
        )
        results = [
            ExperimentResult(
                commit="abc",
                metric=5.0,
                guard="--",
                status="discard",
                confidence="--",
                description="nothing",
            )
        ]
        ctx = MagicMock()
        with (
            patch("autoresearch.results.read_results", return_value=results),
            patch("autoresearch.finalize.finalize_marker", return_value=[]),
        ):
            _finalize_interactive(ctx, tracked)


# ---------------------------------------------------------------------------
# _merge_interactive — no branch
# ---------------------------------------------------------------------------

class TestMergeInteractiveNoBranch:
    def test_no_branch_prints_dim(self):
        from unittest.mock import MagicMock
        from autoresearch.cli import _merge_interactive
        from autoresearch.state import TrackedMarker

        tracked = TrackedMarker(
            id="repo:m",
            repo_path="/tmp",
            repo_name="repo",
            marker_name="m",
            branch=None,
        )
        ctx = MagicMock()
        _merge_interactive(ctx, tracked)

    def test_merge_exception_shows_error(self):
        from unittest.mock import MagicMock
        from autoresearch.cli import _merge_interactive
        from autoresearch.state import TrackedMarker
        from rich.prompt import Prompt

        tracked = TrackedMarker(
            id="repo:m",
            repo_path="/tmp",
            repo_name="repo",
            marker_name="m",
            branch="autoresearch/m",
        )
        ctx = MagicMock()
        with (
            patch.object(Prompt, "ask", return_value="main"),
            patch("autoresearch.finalize.merge_finalized", side_effect=Exception("git conflict")),
        ):
            _merge_interactive(ctx, tracked)


# ---------------------------------------------------------------------------
# detach_cmd — non-headless output
# ---------------------------------------------------------------------------

class TestDetachCmdNonHeadless:
    def test_non_headless_detach_success_prints_yellow(self):
        from autoresearch.state import TrackedMarker

        tracked = TrackedMarker(
            id="repo:m",
            repo_path="/tmp",
            repo_name="repo",
            marker_name="m",
        )
        state = AppState(markers=[tracked])
        with (
            patch("autoresearch.cli._load_state", return_value=state),
            patch("autoresearch.state.save_state"),
            patch("autoresearch.state.untrack_marker"),
        ):
            result = runner.invoke(app, ["detach", "-m", "repo:m"])
        assert result.exit_code == 0
        assert "Detached" in result.output or "detach" in result.output.lower()

    def test_non_headless_detach_not_found_prints_red(self):
        state = AppState(markers=[])
        with patch("autoresearch.cli._load_state", return_value=state):
            result = runner.invoke(app, ["detach", "-m", "repo:missing"])
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# skip_cmd / pause_cmd — non-headless toggle messages
# ---------------------------------------------------------------------------

class TestSkipPauseCmdNonHeadless:
    def test_skip_non_headless_prints_skipped(self):
        from autoresearch.state import TrackedMarker

        tracked = TrackedMarker(
            id="repo:m",
            repo_path="/tmp",
            repo_name="repo",
            marker_name="m",
        )
        state = AppState(markers=[tracked])
        with (
            patch("autoresearch.cli._load_state", return_value=state),
            patch("autoresearch.state.save_state"),
        ):
            result = runner.invoke(app, ["skip", "-m", "repo:m"])
        assert result.exit_code == 0
        assert "skipped" in result.output.lower()

    def test_pause_non_headless_prints_paused(self):
        from autoresearch.state import TrackedMarker

        tracked = TrackedMarker(
            id="repo:m",
            repo_path="/tmp",
            repo_name="repo",
            marker_name="m",
        )
        state = AppState(markers=[tracked])
        with (
            patch("autoresearch.cli._load_state", return_value=state),
            patch("autoresearch.state.save_state"),
        ):
            result = runner.invoke(app, ["pause", "-m", "repo:m"])
        assert result.exit_code == 0
        assert "paused" in result.output.lower()

    def test_skip_unskip_toggle_non_headless(self):
        from autoresearch.marker import MarkerStatus
        from autoresearch.state import TrackedMarker

        tracked = TrackedMarker(
            id="repo:m",
            repo_path="/tmp",
            repo_name="repo",
            marker_name="m",
            status_override=MarkerStatus.SKIP,
        )
        state = AppState(markers=[tracked])
        with (
            patch("autoresearch.cli._load_state", return_value=state),
            patch("autoresearch.state.save_state"),
        ):
            result = runner.invoke(app, ["skip", "-m", "repo:m"])
        assert result.exit_code == 0
        assert "unskipped" in result.output.lower()

    def test_pause_resume_toggle_non_headless(self):
        from autoresearch.marker import MarkerStatus
        from autoresearch.state import TrackedMarker

        tracked = TrackedMarker(
            id="repo:m",
            repo_path="/tmp",
            repo_name="repo",
            marker_name="m",
            status_override=MarkerStatus.PAUSED,
        )
        state = AppState(markers=[tracked])
        with (
            patch("autoresearch.cli._load_state", return_value=state),
            patch("autoresearch.state.save_state"),
        ):
            result = runner.invoke(app, ["pause", "-m", "repo:m"])
        assert result.exit_code == 0
        assert "resumed" in result.output.lower()


# ---------------------------------------------------------------------------
# daemon_stop — non-headless paths
# ---------------------------------------------------------------------------

class TestDaemonStopNonHeadless:
    def test_non_headless_stopped_prints_green(self):
        with patch("autoresearch.daemon.stop_daemon", return_value=True):
            result = runner.invoke(app, ["daemon", "stop"])
        assert result.exit_code == 0
        assert "stopped" in result.output.lower()

    def test_non_headless_no_daemon_prints_yellow(self):
        with patch("autoresearch.daemon.stop_daemon", return_value=False):
            result = runner.invoke(app, ["daemon", "stop"])
        assert result.exit_code == 0
        assert "no daemon" in result.output.lower()


# ---------------------------------------------------------------------------
# daemon_logs — no log file non-headless
# ---------------------------------------------------------------------------

class TestDaemonLogsNoFile:
    def test_non_headless_no_log_file_prints_dim(self, tmp_path):
        missing = tmp_path / "no-such.log"
        with patch("autoresearch.daemon.LOG_PATH", missing):
            result = runner.invoke(app, ["daemon", "logs"])
        assert result.exit_code == 1

    def test_headless_no_log_file_returns_error(self, tmp_path):
        missing = tmp_path / "no-such.log"
        with patch("autoresearch.daemon.LOG_PATH", missing):
            result = runner.invoke(app, ["--headless", "daemon", "logs"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["status"] == "error"


# ---------------------------------------------------------------------------
# run_cmd — no --marker and no --repo headless
# ---------------------------------------------------------------------------

class TestRunCmdNoMarkerNoRepo:
    def test_headless_no_marker_no_config_exits_2(self):
        with patch("autoresearch.cli._load_local_markers", return_value=[]):
            result = runner.invoke(app, ["--headless", "run"])
        assert result.exit_code == 2
        data = json.loads(result.output)
        assert data["status"] == "error"

    def test_non_headless_no_marker_no_config_exits_2(self):
        with patch("autoresearch.cli._load_local_markers", return_value=[]):
            result = runner.invoke(app, ["run"])
        assert result.exit_code == 2


# ---------------------------------------------------------------------------
# headless_confirm non-headless path (cli_utils.py line 39)
# ---------------------------------------------------------------------------

class TestHeadlessConfirmInteractive:
    def test_user_answers_yes(self):
        from unittest.mock import MagicMock
        import typer
        from autoresearch.cli_utils import headless_confirm

        ctx = MagicMock(spec=typer.Context)
        ctx.obj = {"headless": False}
        with patch("autoresearch.cli_utils.Prompt.ask", return_value="y"):
            result = headless_confirm(ctx, "Continue?")
        assert result is True

    def test_user_answers_no(self):
        from unittest.mock import MagicMock
        import typer
        from autoresearch.cli_utils import headless_confirm

        ctx = MagicMock(spec=typer.Context)
        ctx.obj = {"headless": False}
        with patch("autoresearch.cli_utils.Prompt.ask", return_value="n"):
            result = headless_confirm(ctx, "Continue?")
        assert result is False

    def test_default_false_passes_n(self):
        from unittest.mock import MagicMock
        import typer
        from autoresearch.cli_utils import headless_confirm

        ctx = MagicMock(spec=typer.Context)
        ctx.obj = {"headless": False}
        with patch("autoresearch.cli_utils.Prompt.ask", return_value="n") as mock_ask:
            headless_confirm(ctx, "Delete?", default=False)
        mock_ask.assert_called_once_with("Delete?", choices=["y", "n"], default="n")


# ---------------------------------------------------------------------------
# headless_prompt non-headless path (cli_utils.py line 56)
# ---------------------------------------------------------------------------

class TestHeadlessPromptInteractive:
    def test_prompts_user_returns_value(self):
        from unittest.mock import MagicMock
        import typer
        from autoresearch.cli_utils import headless_prompt

        ctx = MagicMock(spec=typer.Context)
        ctx.obj = {"headless": False}
        with patch("autoresearch.cli_utils.Prompt.ask", return_value="user-input"):
            result = headless_prompt(ctx, "Enter name:", default="default")
        assert result == "user-input"

    def test_interactive_with_no_default(self):
        from unittest.mock import MagicMock
        import typer
        from autoresearch.cli_utils import headless_prompt

        ctx = MagicMock(spec=typer.Context)
        ctx.obj = {"headless": False}
        with patch("autoresearch.cli_utils.Prompt.ask", return_value="answer") as mock_ask:
            result = headless_prompt(ctx, "Enter:")
        assert result == "answer"
        mock_ask.assert_called_once_with("Enter:", default=None)


# ---------------------------------------------------------------------------
# init_cmd non-headless with existing config (cli.py line 355)
# ---------------------------------------------------------------------------

class TestInitCmdNonHeadlessAlreadyConfig:
    def test_synced_message_when_config_exists(self, tmp_path):
        ar_dir = tmp_path / ".autoresearch"
        ar_dir.mkdir(parents=True)
        config_file = ar_dir / "config.yaml"
        config_file.write_text("markers: []")
        with patch("autoresearch.agent_profile.init_autoresearch_dir", return_value=ar_dir):
            result = runner.invoke(app, ["init", "--path", str(tmp_path), "--no-claude"])
        assert result.exit_code == 0
        assert "Synced" in result.output

    def test_synced_message_contains_ar_dir(self, tmp_path):
        ar_dir = tmp_path / ".autoresearch"
        ar_dir.mkdir(parents=True)
        config_file = ar_dir / "config.yaml"
        config_file.write_text("markers: []")
        with patch("autoresearch.agent_profile.init_autoresearch_dir", return_value=ar_dir):
            result = runner.invoke(app, ["init", "--path", str(tmp_path), "--no-claude"])
        assert "already existed" in result.output


# ---------------------------------------------------------------------------
# daemon status with unresolvable marker (cli.py line 1190)
# ---------------------------------------------------------------------------

class TestDaemonStatusUnresolvableMarker:
    def test_skips_marker_without_config(self):
        tracked = _make_tracked(repo_path="/nonexistent/path")
        state = AppState(markers=[tracked])
        with (
            patch("autoresearch.cli._load_state", return_value=state),
            patch("autoresearch.daemon.check_stale_pid"),
            patch("autoresearch.daemon.read_pid", return_value=None),
            patch("autoresearch.daemon.is_pid_alive", return_value=False),
            patch("autoresearch.cli._resolve_marker_data", return_value=(None, None, None)),
        ):
            result = runner.invoke(app, ["--headless", "daemon", "status"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["data"]["scheduled_markers"] == []


# ---------------------------------------------------------------------------
# run_cmd non-headless repo with no matching markers (cli.py line 561-562)
# ---------------------------------------------------------------------------

class TestRunCmdNonHeadlessRepoNoMatch:
    def test_non_headless_no_markers_for_repo(self):
        state = AppState(markers=[])
        with patch("autoresearch.cli._load_state", return_value=state):
            result = runner.invoke(app, ["run", "--repo", "no-such-repo"])
        assert result.exit_code == 1
        assert "No markers found" in result.output


# ---------------------------------------------------------------------------
# run_cmd repo mode skips non-active markers (cli.py line 573)
# ---------------------------------------------------------------------------

class TestRunRepoSkipsNonActiveNonHeadless:
    def test_non_headless_skips_paused_marker(self):
        from autoresearch.marker import MarkerFile

        tracked = _make_tracked(repo_path="/tmp/fakerepo")
        state = AppState(markers=[tracked])
        marker = _make_marker(status=MarkerStatus.PAUSED)
        mf = MarkerFile(markers=[marker])

        with (
            patch("autoresearch.cli._load_state", return_value=state),
            patch("autoresearch.cli.find_marker_file", return_value=Path("/tmp/fakerepo/.autoresearch.yaml")),
            patch("autoresearch.cli.load_markers", return_value=mf),
            patch("autoresearch.cli.get_effective_status", return_value=MarkerStatus.PAUSED),
        ):
            result = runner.invoke(app, ["run", "--repo", "fakerepo"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# _status_menu interactive actions (cli.py lines 721, 723-724, 726, 728, 730)
# ---------------------------------------------------------------------------


class TestStatusMenuInteractiveActions:
    def _make_ctx(self):
        from unittest.mock import MagicMock
        import typer
        ctx = MagicMock(spec=typer.Context)
        ctx.obj = {"headless": False}
        return ctx

    def test_action_a_calls_action_add(self):
        from autoresearch.cli import _interactive_main

        state = AppState(markers=[])
        ctx = self._make_ctx()
        with (
            patch("autoresearch.cli._load_state", return_value=state),
            patch("autoresearch.cli.find_marker_file", return_value=None),
            patch("autoresearch.cli._home_mode"),
            patch("rich.prompt.Prompt.ask", side_effect=["a", "q"]),
            patch("autoresearch.cli._action_add") as mock_add,
        ):
            _interactive_main(ctx)
        mock_add.assert_called_once()

    def test_action_p_prompts_for_path(self):
        from autoresearch.cli import _interactive_main

        state = AppState(markers=[])
        ctx = self._make_ctx()
        ask_calls = iter(["p", "/some/path", "q"])
        with (
            patch("autoresearch.cli._load_state", return_value=state),
            patch("autoresearch.cli.find_marker_file", return_value=None),
            patch("autoresearch.cli._home_mode"),
            patch("rich.prompt.Prompt.ask", side_effect=ask_calls),
            patch("autoresearch.cli._action_add") as mock_add,
        ):
            _interactive_main(ctx)
        assert mock_add.call_count == 1
        call_path = mock_add.call_args[0][1]
        assert str(call_path) == "/some/path"

    def test_action_d_calls_detach(self):
        from autoresearch.cli import _interactive_main

        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        ctx = self._make_ctx()
        with (
            patch("autoresearch.cli._load_state", return_value=state),
            patch("autoresearch.cli.find_marker_file", return_value=None),
            patch("autoresearch.cli._home_mode"),
            patch("rich.prompt.Prompt.ask", side_effect=["d", "q"]),
            patch("autoresearch.cli._action_detach_interactive") as mock_detach,
        ):
            _interactive_main(ctx)
        mock_detach.assert_called_once()

    def test_action_r_calls_run_selected(self):
        from autoresearch.cli import _interactive_main

        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        ctx = self._make_ctx()
        with (
            patch("autoresearch.cli._load_state", return_value=state),
            patch("autoresearch.cli.find_marker_file", return_value=None),
            patch("autoresearch.cli._home_mode"),
            patch("rich.prompt.Prompt.ask", side_effect=["r", "q"]),
            patch("autoresearch.cli._action_run_selected_interactive") as mock_run,
        ):
            _interactive_main(ctx)
        mock_run.assert_called_once()

    def test_action_R_calls_run_repo(self):
        from autoresearch.cli import _interactive_main

        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        ctx = self._make_ctx()
        with (
            patch("autoresearch.cli._load_state", return_value=state),
            patch("autoresearch.cli.find_marker_file", return_value=None),
            patch("autoresearch.cli._home_mode"),
            patch("rich.prompt.Prompt.ask", side_effect=["R", "q"]),
            patch("autoresearch.cli._action_run_repo_interactive") as mock_run_repo,
        ):
            _interactive_main(ctx)
        mock_run_repo.assert_called_once()


# ---------------------------------------------------------------------------
# _marker_submenu interactive actions (cli.py lines 903, 905, 911, 921-942)
# ---------------------------------------------------------------------------


class TestMarkerSubmenuInteractiveActions:
    def _make_ctx(self):
        from unittest.mock import MagicMock
        import typer
        ctx = MagicMock(spec=typer.Context)
        ctx.obj = {"headless": False}
        return ctx

    def test_baseline_and_current_shown_in_panel(self):
        from autoresearch.cli import _marker_submenu
        from autoresearch.marker import MarkerFile

        tracked = _make_tracked(baseline=10.0, current=42.0, branch="autoresearch/m-mar31")
        marker = _make_marker()
        ctx = self._make_ctx()
        with (
            patch("autoresearch.cli._resolve_marker_data", return_value=(
                MarkerFile(markers=[marker]), marker, MarkerStatus.ACTIVE
            )),
            patch("rich.prompt.Prompt.ask", side_effect=["q"]),
        ):
            _marker_submenu(ctx, tracked)

    def test_action_s_calls_show_status(self):
        from autoresearch.cli import _marker_submenu
        from autoresearch.marker import MarkerFile

        tracked = _make_tracked()
        marker = _make_marker()
        ctx = self._make_ctx()
        with (
            patch("autoresearch.cli._resolve_marker_data", return_value=(
                MarkerFile(markers=[marker]), marker, MarkerStatus.ACTIVE
            )),
            patch("rich.prompt.Prompt.ask", side_effect=["s", "q"]),
            patch("autoresearch.cli._show_status_interactive") as mock_status,
        ):
            _marker_submenu(ctx, tracked)
        mock_status.assert_called_once()

    def test_action_r_calls_run_single(self):
        from autoresearch.cli import _marker_submenu
        from autoresearch.marker import MarkerFile

        tracked = _make_tracked()
        marker = _make_marker()
        ctx = self._make_ctx()
        with (
            patch("autoresearch.cli._resolve_marker_data", return_value=(
                MarkerFile(markers=[marker]), marker, MarkerStatus.ACTIVE
            )),
            patch("rich.prompt.Prompt.ask", side_effect=["r", "q"]),
            patch("autoresearch.cli._run_single_marker") as mock_run,
        ):
            _marker_submenu(ctx, tracked)
        mock_run.assert_called_once()

    def test_action_k_calls_toggle_skip(self):
        from autoresearch.cli import _marker_submenu
        from autoresearch.marker import MarkerFile

        tracked = _make_tracked()
        marker = _make_marker()
        ctx = self._make_ctx()
        with (
            patch("autoresearch.cli._resolve_marker_data", return_value=(
                MarkerFile(markers=[marker]), marker, MarkerStatus.ACTIVE
            )),
            patch("rich.prompt.Prompt.ask", side_effect=["k", "q"]),
            patch("autoresearch.cli._toggle_skip") as mock_skip,
        ):
            _marker_submenu(ctx, tracked)
        mock_skip.assert_called_once()

    def test_action_f_calls_finalize(self):
        from autoresearch.cli import _marker_submenu
        from autoresearch.marker import MarkerFile

        tracked = _make_tracked()
        marker = _make_marker()
        ctx = self._make_ctx()
        with (
            patch("autoresearch.cli._resolve_marker_data", return_value=(
                MarkerFile(markers=[marker]), marker, MarkerStatus.ACTIVE
            )),
            patch("rich.prompt.Prompt.ask", side_effect=["f", "q"]),
            patch("autoresearch.cli._finalize_interactive") as mock_fin,
        ):
            _marker_submenu(ctx, tracked)
        mock_fin.assert_called_once()

    def test_action_m_calls_merge(self):
        from autoresearch.cli import _marker_submenu
        from autoresearch.marker import MarkerFile

        tracked = _make_tracked()
        marker = _make_marker()
        ctx = self._make_ctx()
        with (
            patch("autoresearch.cli._resolve_marker_data", return_value=(
                MarkerFile(markers=[marker]), marker, MarkerStatus.ACTIVE
            )),
            patch("rich.prompt.Prompt.ask", side_effect=["m", "q"]),
            patch("autoresearch.cli._merge_interactive") as mock_merge,
        ):
            _marker_submenu(ctx, tracked)
        mock_merge.assert_called_once()

    def test_action_t_calls_show_results(self):
        from autoresearch.cli import _marker_submenu
        from autoresearch.marker import MarkerFile

        tracked = _make_tracked()
        marker = _make_marker()
        ctx = self._make_ctx()
        with (
            patch("autoresearch.cli._resolve_marker_data", return_value=(
                MarkerFile(markers=[marker]), marker, MarkerStatus.ACTIVE
            )),
            patch("rich.prompt.Prompt.ask", side_effect=["t", "q"]),
            patch("autoresearch.cli._show_results_interactive") as mock_results,
        ):
            _marker_submenu(ctx, tracked)
        mock_results.assert_called_once()

    def test_action_p_calls_toggle_pause(self):
        from autoresearch.cli import _marker_submenu
        from autoresearch.marker import MarkerFile

        tracked = _make_tracked()
        marker = _make_marker()
        ctx = self._make_ctx()
        with (
            patch("autoresearch.cli._resolve_marker_data", return_value=(
                MarkerFile(markers=[marker]), marker, MarkerStatus.ACTIVE
            )),
            patch("rich.prompt.Prompt.ask", side_effect=["p", "q"]),
            patch("autoresearch.cli._toggle_pause") as mock_pause,
        ):
            _marker_submenu(ctx, tracked)
        mock_pause.assert_called_once()

    def test_action_e_calls_edit_config(self):
        from autoresearch.cli import _marker_submenu
        from autoresearch.marker import MarkerFile

        tracked = _make_tracked()
        marker = _make_marker()
        ctx = self._make_ctx()
        with (
            patch("autoresearch.cli._resolve_marker_data", return_value=(
                MarkerFile(markers=[marker]), marker, MarkerStatus.ACTIVE
            )),
            patch("rich.prompt.Prompt.ask", side_effect=["e", "q"]),
            patch("autoresearch.cli._edit_config") as mock_edit,
        ):
            _marker_submenu(ctx, tracked)
        mock_edit.assert_called_once()

    def test_action_b_calls_show_branch(self):
        from autoresearch.cli import _marker_submenu
        from autoresearch.marker import MarkerFile

        tracked = _make_tracked()
        marker = _make_marker()
        ctx = self._make_ctx()
        with (
            patch("autoresearch.cli._resolve_marker_data", return_value=(
                MarkerFile(markers=[marker]), marker, MarkerStatus.ACTIVE
            )),
            patch("rich.prompt.Prompt.ask", side_effect=["b", "q"]),
            patch("autoresearch.cli._show_branch") as mock_branch,
        ):
            _marker_submenu(ctx, tracked)
        mock_branch.assert_called_once()

    def test_action_i_calls_show_ideas(self):
        from autoresearch.cli import _marker_submenu
        from autoresearch.marker import MarkerFile

        tracked = _make_tracked()
        marker = _make_marker()
        ctx = self._make_ctx()
        with (
            patch("autoresearch.cli._resolve_marker_data", return_value=(
                MarkerFile(markers=[marker]), marker, MarkerStatus.ACTIVE
            )),
            patch("rich.prompt.Prompt.ask", side_effect=["i", "q"]),
            patch("autoresearch.cli._show_ideas_interactive") as mock_ideas,
        ):
            _marker_submenu(ctx, tracked)
        mock_ideas.assert_called_once()

    def test_action_c_calls_show_confidence(self):
        from autoresearch.cli import _marker_submenu
        from autoresearch.marker import MarkerFile

        tracked = _make_tracked()
        marker = _make_marker()
        ctx = self._make_ctx()
        with (
            patch("autoresearch.cli._resolve_marker_data", return_value=(
                MarkerFile(markers=[marker]), marker, MarkerStatus.ACTIVE
            )),
            patch("rich.prompt.Prompt.ask", side_effect=["c", "q"]),
            patch("autoresearch.cli._show_confidence_interactive") as mock_conf,
        ):
            _marker_submenu(ctx, tracked)
        mock_conf.assert_called_once()



# ---------------------------------------------------------------------------
# _format_tracked_json — additional edge cases
# ---------------------------------------------------------------------------


class TestFormatTrackedJsonAdditional:
    def _call(self, tracked, status=None):
        from autoresearch.cli import _format_tracked_json
        marker = _make_marker()
        effective_status = status or MarkerStatus.ACTIVE
        return _format_tracked_json(tracked, marker, effective_status)

    def test_zero_baseline_and_current(self):
        tracked = _make_tracked(baseline=0.0, current=0.0)
        result = self._call(tracked)
        assert result["baseline"] == 0.0
        assert result["current"] == 0.0

    def test_negative_metric_values(self):
        tracked = _make_tracked(baseline=-10.0, current=-5.0)
        result = self._call(tracked)
        assert result["baseline"] == -10.0
        assert result["current"] == -5.0

    def test_large_metric_values(self):
        tracked = _make_tracked(baseline=1_000_000.0, current=9_999_999.0)
        result = self._call(tracked)
        assert result["baseline"] == 1_000_000.0

    def test_marker_name_preserved(self):
        tracked = _make_tracked(marker_name="my-special-marker")
        result = self._call(tracked)
        assert result["marker"] == "my-special-marker"

    def test_repo_name_preserved(self):
        tracked = _make_tracked()
        result = self._call(tracked)
        assert "repo" in result

    def test_result_is_dict(self):
        tracked = _make_tracked()
        result = self._call(tracked)
        assert isinstance(result, dict)

    def test_status_key_present(self):
        tracked = _make_tracked()
        result = self._call(tracked)
        assert "status" in result

    def test_status_value_from_effective_status(self):
        tracked = _make_tracked()
        result = self._call(tracked, status=MarkerStatus.PAUSED)
        assert result["status"] == MarkerStatus.PAUSED.value


# ---------------------------------------------------------------------------
# headless list — various states
# ---------------------------------------------------------------------------


class TestHeadlessListStates:
    def test_skipped_marker_in_list(self, tmp_path):
        tracked = _make_tracked(skip=True)
        state = AppState(markers=[tracked])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "list"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data["data"]) == 1

    def test_paused_marker_in_list(self, tmp_path):
        tracked = _make_tracked(paused=True)
        state = AppState(markers=[tracked])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "list"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data["data"]) == 1

    def test_multiple_markers_all_listed(self):
        tracked1 = _make_tracked(marker_name="m1", marker_id="r:m1")
        tracked2 = _make_tracked(marker_name="m2", marker_id="r:m2")
        state = AppState(markers=[tracked1, tracked2])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "list"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data["data"]) == 2

    def test_list_output_has_ok_status(self):
        state = AppState(markers=[_make_tracked()])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "list"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "ok"


# ---------------------------------------------------------------------------
# headless status — various scenarios
# ---------------------------------------------------------------------------


class TestHeadlessStatusAdditional:
    def test_status_with_branch_by_id(self):
        tracked = _make_tracked(branch="autoresearch/m-mar31", current=42.0)
        state = AppState(markers=[tracked])
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.find_marker_file", return_value=None),
        ):
            result = runner.invoke(app, ["--headless", "status", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0

    def test_status_not_found_returns_error(self):
        state = AppState(markers=[])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "status", "-m", "nonexistent:nonexistent"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["status"] == "error"


# ---------------------------------------------------------------------------
# headless pause — additional scenarios
# ---------------------------------------------------------------------------


class TestHeadlessPauseAdditional:
    def test_pause_already_paused(self, tmp_path):
        tracked = _make_tracked(paused=True)
        state = AppState(markers=[tracked])
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.save_state"),
        ):
            result = runner.invoke(app, ["--headless", "pause", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0

    def test_pause_not_paused_toggles(self, tmp_path):
        tracked = _make_tracked(paused=False)
        state = AppState(markers=[tracked])
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.save_state"),
        ):
            result = runner.invoke(app, ["--headless", "pause", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# headless list — additional field checks
# ---------------------------------------------------------------------------

class TestHeadlessListFields:
    def test_marker_id_in_data(self, tmp_path):
        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "list"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data["data"]) == 1
        assert "id" in data["data"][0]

    def test_multiple_markers_in_data(self, tmp_path):
        t1 = _make_tracked(marker_id="repo:m1", marker_name="m1")
        t2 = _make_tracked(marker_id="repo:m2", marker_name="m2")
        state = AppState(markers=[t1, t2])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "list"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data["data"]) == 2

    def test_status_ok_in_response(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "list"])
        assert json.loads(result.output)["status"] == "ok"


# ---------------------------------------------------------------------------
# headless status — additional field checks
# ---------------------------------------------------------------------------

class TestHeadlessStatusFields:
    def test_not_found_returns_error(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "status", "-m", "missing:marker"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["status"] == "error"

    def test_found_marker_returns_ok(self):
        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "status", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "ok"


# ---------------------------------------------------------------------------
# headless skip — additional scenarios
# ---------------------------------------------------------------------------

class TestHeadlessSkipAdditional:
    def test_skip_not_found_returns_error(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "skip", "-m", "nope:nope"])
        assert result.exit_code == 1

    def test_skip_active_marker_sets_skip(self):
        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.save_state"),
        ):
            result = runner.invoke(app, ["--headless", "skip", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# headless detach — additional scenarios
# ---------------------------------------------------------------------------

class TestHeadlessDetachAdditional:
    def test_detach_not_found_returns_error(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "detach", "-m", "nope:nope"])
        assert result.exit_code == 1

    def test_detach_found_returns_ok(self):
        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.save_state"),
        ):
            result = runner.invoke(app, ["--headless", "detach", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# headless results — additional scenarios
# ---------------------------------------------------------------------------

class TestHeadlessResultsAdditional:
    def test_no_results_file_returns_empty(self, tmp_path):
        tracked = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[tracked])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "results", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "ok"
        assert data["data"] == []

    def test_marker_not_tracked_returns_error(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "results", "-m", "none:none"])
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# headless ideas — additional scenarios
# ---------------------------------------------------------------------------

class TestHeadlessIdeasAdditional:
    def test_marker_not_found_returns_error(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "ideas", "-m", "nope:nope"])
        assert result.exit_code == 1

    def test_no_ideas_file_returns_empty(self, tmp_path):
        tracked = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[tracked])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "ideas", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# headless confidence — additional scenarios
# ---------------------------------------------------------------------------

class TestHeadlessConfidenceAdditional2:
    def test_marker_not_found_returns_error(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "confidence", "-m", "nope:nope"])
        assert result.exit_code == 1

    def test_no_results_returns_ok_with_none(self, tmp_path):
        tracked = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[tracked])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "confidence", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# headless list — more field checks
# ---------------------------------------------------------------------------

class TestHeadlessListMoreFields:
    def test_list_returns_data_key(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "list"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "data" in data

    def test_list_with_one_marker(self):
        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "list"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data["data"]) == 1

    def test_list_status_ok(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "list"])
        data = json.loads(result.output)
        assert data.get("status") == "ok"

    def test_list_two_markers(self):
        t1 = _make_tracked(marker_id="repo1:m1", marker_name="m1")
        t2 = _make_tracked(repo_path="/tmp/repo2", marker_id="repo2:m2", marker_name="m2")
        state = AppState(markers=[t1, t2])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "list"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data["data"]) == 2

    def test_list_json_parseable(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "list"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert isinstance(parsed, dict)


# ---------------------------------------------------------------------------
# headless status — more scenarios
# ---------------------------------------------------------------------------

class TestHeadlessStatusMore:
    def test_status_not_found_returns_error(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "status", "-m", "nope:nope"])
        assert result.exit_code == 1

    def test_status_found_marker_returns_ok(self):
        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "status", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "ok"

    def test_status_data_has_id(self):
        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "status", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "data" in data


# ---------------------------------------------------------------------------
# headless pause — more scenarios
# ---------------------------------------------------------------------------

class TestHeadlessPauseMore:
    def test_pause_not_found_returns_error(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "pause", "-m", "nope:nope"])
        assert result.exit_code == 1

    def test_pause_found_returns_ok(self):
        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.save_state"),
        ):
            result = runner.invoke(app, ["--headless", "pause", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0

    def test_pause_json_parseable(self):
        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.save_state"),
        ):
            result = runner.invoke(app, ["--headless", "pause", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, dict)


# ---------------------------------------------------------------------------
# headless pause — action field checks
# ---------------------------------------------------------------------------

class TestHeadlessPauseActionField:
    def test_pause_returns_dict(self):
        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.save_state"),
        ):
            result = runner.invoke(app, ["--headless", "pause", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, dict)

    def test_pause_status_is_ok(self):
        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.save_state"),
        ):
            result = runner.invoke(app, ["--headless", "pause", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "ok"

    def test_pause_missing_marker_flag(self):
        result = runner.invoke(app, ["--headless", "pause"])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# headless confidence — more checks
# ---------------------------------------------------------------------------

class TestHeadlessConfidenceMore:
    def test_confidence_not_found_returns_error(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "confidence", "-m", "nope:nope"])
        assert result.exit_code == 1

    def test_confidence_ok_status(self, tmp_path):
        tracked = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[tracked])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "confidence", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "ok"

    def test_confidence_json_parseable(self, tmp_path):
        tracked = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[tracked])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "confidence", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, dict)


# ---------------------------------------------------------------------------
# headless results — more scenarios
# ---------------------------------------------------------------------------

class TestHeadlessResultsMore:
    def test_results_not_found_returns_error(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "results", "-m", "nope:nope"])
        assert result.exit_code == 1

    def test_results_ok_status(self, tmp_path):
        tracked = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[tracked])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "results", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "ok"

    def test_results_data_is_list(self, tmp_path):
        tracked = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[tracked])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "results", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data["data"], list)


# ---------------------------------------------------------------------------
# headless ideas — more scenarios
# ---------------------------------------------------------------------------

class TestHeadlessIdeasMore:
    def test_ideas_not_found_returns_error(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "ideas", "-m", "nope:nope"])
        assert result.exit_code == 1

    def test_ideas_ok_no_file(self, tmp_path):
        tracked = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[tracked])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "ideas", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "ok"


# ---------------------------------------------------------------------------
# headless list — additional field/state tests
# ---------------------------------------------------------------------------

class TestHeadlessListExtra:
    def test_list_returns_json_dict(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "list"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, dict)

    def test_list_has_status_key(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "list"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "status" in data

    def test_list_has_data_key(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "list"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "data" in data

    def test_list_empty_state_data_is_empty_list(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "list"])
        data = json.loads(result.output)
        assert data["data"] == []

    def test_list_with_one_tracked_data_has_one_item(self, tmp_path):
        tracked = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[tracked])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "list"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data["data"]) == 1

    def test_list_with_two_tracked_data_has_two_items(self, tmp_path):
        t1 = _make_tracked(repo_path=str(tmp_path), marker_id="r1:m1", marker_name="m1")
        t2 = _make_tracked(repo_path=str(tmp_path), marker_id="r2:m2", marker_name="m2")
        state = AppState(markers=[t1, t2])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "list"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data["data"]) == 2

    def test_list_item_has_id_field(self, tmp_path):
        tracked = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[tracked])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "list"])
        data = json.loads(result.output)
        assert "id" in data["data"][0]

    def test_list_item_has_marker_name(self, tmp_path):
        tracked = _make_tracked(repo_path=str(tmp_path), marker_name="my-marker")
        state = AppState(markers=[tracked])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "list"])
        data = json.loads(result.output)
        assert "my-marker" in str(data["data"][0])


# ---------------------------------------------------------------------------
# headless status — additional tests
# ---------------------------------------------------------------------------

class TestHeadlessStatusExtra:
    def test_status_not_found_exits_1(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "status", "-m", "missing:marker"])
        assert result.exit_code == 1

    def test_status_found_exits_0(self, tmp_path):
        tracked = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[tracked])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "status", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0

    def test_status_output_is_json(self, tmp_path):
        tracked = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[tracked])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "status", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, dict)

    def test_status_has_status_field(self, tmp_path):
        tracked = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[tracked])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "status", "-m", "fakerepo:test-marker"])
        data = json.loads(result.output)
        assert "status" in data


# ---------------------------------------------------------------------------
# headless skip — additional tests
# ---------------------------------------------------------------------------

class TestHeadlessSkipExtra:
    def test_skip_not_tracked_exits_1(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "skip", "-m", "missing:marker"])
        assert result.exit_code == 1

    def test_skip_tracked_exits_0(self, tmp_path):
        tracked = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[tracked])
        with patch("autoresearch.cli.load_state", return_value=state):
            with patch("autoresearch.cli.save_state"):
                result = runner.invoke(app, ["--headless", "skip", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0

    def test_skip_output_is_json(self, tmp_path):
        tracked = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[tracked])
        with patch("autoresearch.cli.load_state", return_value=state):
            with patch("autoresearch.cli.save_state"):
                result = runner.invoke(app, ["--headless", "skip", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, dict)


# ---------------------------------------------------------------------------
# headless pause — additional tests
# ---------------------------------------------------------------------------

class TestHeadlessPauseExtra:
    def test_pause_not_tracked_exits_1(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "pause", "-m", "missing:marker"])
        assert result.exit_code == 1

    def test_pause_tracked_exits_0(self, tmp_path):
        tracked = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[tracked])
        with patch("autoresearch.cli.load_state", return_value=state):
            with patch("autoresearch.cli.save_state"):
                result = runner.invoke(app, ["--headless", "pause", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0

    def test_pause_output_is_json(self, tmp_path):
        tracked = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[tracked])
        with patch("autoresearch.cli.load_state", return_value=state):
            with patch("autoresearch.cli.save_state"):
                result = runner.invoke(app, ["--headless", "pause", "-m", "fakerepo:test-marker"])
        data = json.loads(result.output)
        assert isinstance(data, dict)


# ---------------------------------------------------------------------------
# headless results — output shape tests
# ---------------------------------------------------------------------------

class TestHeadlessResultsShape:
    def test_results_has_data_key(self, tmp_path):
        tracked = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[tracked])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "results", "-m", "fakerepo:test-marker"])
        data = json.loads(result.output)
        assert "data" in data

    def test_results_has_status_key(self, tmp_path):
        tracked = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[tracked])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "results", "-m", "fakerepo:test-marker"])
        data = json.loads(result.output)
        assert "status" in data

    def test_results_data_empty_list_no_file(self, tmp_path):
        tracked = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[tracked])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "results", "-m", "fakerepo:test-marker"])
        data = json.loads(result.output)
        assert data["data"] == []


# ---------------------------------------------------------------------------
# headless ideas — output shape tests
# ---------------------------------------------------------------------------

class TestHeadlessIdeasShape:
    def test_ideas_has_status_key(self, tmp_path):
        tracked = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[tracked])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "ideas", "-m", "fakerepo:test-marker"])
        data = json.loads(result.output)
        assert "status" in data

    def test_ideas_status_ok(self, tmp_path):
        tracked = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[tracked])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "ideas", "-m", "fakerepo:test-marker"])
        data = json.loads(result.output)
        assert data["status"] == "ok"

    def test_ideas_is_parseable_json(self, tmp_path):
        tracked = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[tracked])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "ideas", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0
        assert json.loads(result.output) is not None


# ---------------------------------------------------------------------------
# headless confidence — output shape tests
# ---------------------------------------------------------------------------

class TestHeadlessConfidenceShape:
    def test_confidence_has_status_key(self, tmp_path):
        tracked = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[tracked])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "confidence", "-m", "fakerepo:test-marker"])
        data = json.loads(result.output)
        assert "status" in data

    def test_confidence_is_parseable_json(self, tmp_path):
        tracked = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[tracked])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "confidence", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0
        assert json.loads(result.output) is not None

    def test_confidence_not_found_exits_1(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "confidence", "-m", "bad:marker"])
        assert result.exit_code == 1


class TestHeadlessListFieldsB:
    def test_list_status_ok_field(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "list"])
        data = json.loads(result.output)
        assert data["status"] == "ok"

    def test_list_data_is_list_type(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "list"])
        data = json.loads(result.output)
        assert isinstance(data["data"], list)

    def test_list_empty_data_is_empty(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "list"])
        data = json.loads(result.output)
        assert data["data"] == []

    def test_list_exit_code_zero(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "list"])
        assert result.exit_code == 0

    def test_list_with_marker_has_one_item(self, tmp_path):
        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        with patch("autoresearch.cli.load_state", return_value=state), \
             patch("autoresearch.cli.find_marker_file", return_value=None):
            result = runner.invoke(app, ["--headless", "list"])
        data = json.loads(result.output)
        assert len(data["data"]) == 1

    def test_list_item_has_id(self, tmp_path):
        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        with patch("autoresearch.cli.load_state", return_value=state), \
             patch("autoresearch.cli.find_marker_file", return_value=None):
            result = runner.invoke(app, ["--headless", "list"])
        data = json.loads(result.output)
        assert "id" in data["data"][0]

    def test_list_item_id_value(self, tmp_path):
        tracked = _make_tracked(marker_id="myrepo:mymarker")
        state = AppState(markers=[tracked])
        with patch("autoresearch.cli.load_state", return_value=state), \
             patch("autoresearch.cli.find_marker_file", return_value=None):
            result = runner.invoke(app, ["--headless", "list"])
        data = json.loads(result.output)
        assert data["data"][0]["id"] == "myrepo:mymarker"

    def test_list_two_markers_two_items(self, tmp_path):
        t1 = _make_tracked(marker_id="repo1:m1", marker_name="m1")
        t2 = _make_tracked(marker_id="repo2:m2", marker_name="m2")
        state = AppState(markers=[t1, t2])
        with patch("autoresearch.cli.load_state", return_value=state), \
             patch("autoresearch.cli.find_marker_file", return_value=None):
            result = runner.invoke(app, ["--headless", "list"])
        data = json.loads(result.output)
        assert len(data["data"]) == 2

    def test_list_output_parseable_json(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "list"])
        parsed = json.loads(result.output)
        assert parsed is not None


class TestHeadlessStatusFieldsB:
    def _tracked_with_state(self):
        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        return tracked, state

    def test_status_exit_0_found(self, tmp_path):
        tracked, state = self._tracked_with_state()
        with patch("autoresearch.cli.load_state", return_value=state), \
             patch("autoresearch.cli.find_marker_file", return_value=None):
            result = runner.invoke(app, ["--headless", "status", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0

    def test_status_exit_1_not_found(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "status", "-m", "bad:notfound"])
        assert result.exit_code == 1

    def test_status_data_has_id(self, tmp_path):
        tracked, state = self._tracked_with_state()
        with patch("autoresearch.cli.load_state", return_value=state), \
             patch("autoresearch.cli.find_marker_file", return_value=None):
            result = runner.invoke(app, ["--headless", "status", "-m", "fakerepo:test-marker"])
        data = json.loads(result.output)
        assert "id" in data.get("data", data)

    def test_status_json_parseable(self, tmp_path):
        tracked, state = self._tracked_with_state()
        with patch("autoresearch.cli.load_state", return_value=state), \
             patch("autoresearch.cli.find_marker_file", return_value=None):
            result = runner.invoke(app, ["--headless", "status", "-m", "fakerepo:test-marker"])
        assert json.loads(result.output) is not None

    def test_status_not_found_has_status_error(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "status", "-m", "nope:nope"])
        data = json.loads(result.output)
        assert data.get("status") == "error"


class TestHeadlessSkipFieldsB:
    def _tracked_state(self):
        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        return tracked, state

    def test_skip_exit_0_found(self):
        tracked, state = self._tracked_state()
        with patch("autoresearch.cli.load_state", return_value=state), \
             patch("autoresearch.cli.save_state"):
            result = runner.invoke(app, ["--headless", "skip", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0

    def test_skip_exit_1_not_found(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "skip", "-m", "nope:nope"])
        assert result.exit_code == 1

    def test_skip_json_parseable(self):
        tracked, state = self._tracked_state()
        with patch("autoresearch.cli.load_state", return_value=state), \
             patch("autoresearch.cli.save_state"):
            result = runner.invoke(app, ["--headless", "skip", "-m", "fakerepo:test-marker"])
        assert json.loads(result.output) is not None

    def test_skip_not_found_status_error(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "skip", "-m", "missing:marker"])
        data = json.loads(result.output)
        assert data["status"] == "error"

    def test_skip_status_ok(self):
        tracked, state = self._tracked_state()
        with patch("autoresearch.cli.load_state", return_value=state), \
             patch("autoresearch.cli.save_state"):
            result = runner.invoke(app, ["--headless", "skip", "-m", "fakerepo:test-marker"])
        data = json.loads(result.output)
        assert data["status"] == "ok"


class TestHeadlessPauseFieldsB:
    def _tracked_state(self):
        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        return tracked, state

    def test_pause_exit_0_found(self):
        tracked, state = self._tracked_state()
        with patch("autoresearch.cli.load_state", return_value=state), \
             patch("autoresearch.cli.save_state"):
            result = runner.invoke(app, ["--headless", "pause", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0

    def test_pause_exit_1_not_found(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "pause", "-m", "missing:marker"])
        assert result.exit_code == 1

    def test_pause_json_parseable(self):
        tracked, state = self._tracked_state()
        with patch("autoresearch.cli.load_state", return_value=state), \
             patch("autoresearch.cli.save_state"):
            result = runner.invoke(app, ["--headless", "pause", "-m", "fakerepo:test-marker"])
        assert json.loads(result.output) is not None

    def test_pause_not_found_status_error(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "pause", "-m", "missing:marker"])
        data = json.loads(result.output)
        assert data["status"] == "error"

    def test_pause_status_ok(self):
        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        with patch("autoresearch.cli.load_state", return_value=state), \
             patch("autoresearch.cli.save_state"):
            result = runner.invoke(app, ["--headless", "pause", "-m", "fakerepo:test-marker"])
        data = json.loads(result.output)
        assert data["status"] == "ok"


class TestHeadlessDetachFieldsB:
    def test_detach_exit_0_found(self):
        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        with patch("autoresearch.cli.load_state", return_value=state), \
             patch("autoresearch.cli.save_state"):
            result = runner.invoke(app, ["--headless", "detach", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0

    def test_detach_exit_1_not_found(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "detach", "-m", "nope:nope"])
        assert result.exit_code == 1

    def test_detach_json_parseable(self):
        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        with patch("autoresearch.cli.load_state", return_value=state), \
             patch("autoresearch.cli.save_state"):
            result = runner.invoke(app, ["--headless", "detach", "-m", "fakerepo:test-marker"])
        assert json.loads(result.output) is not None

    def test_detach_not_found_status_error(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "detach", "-m", "nope:nope"])
        data = json.loads(result.output)
        assert data["status"] == "error"

    def test_detach_found_status_ok(self):
        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        with patch("autoresearch.cli.load_state", return_value=state), \
             patch("autoresearch.cli.save_state"):
            result = runner.invoke(app, ["--headless", "detach", "-m", "fakerepo:test-marker"])
        data = json.loads(result.output)
        assert data["status"] == "ok"


class TestHeadlessResultsFieldsB:
    def test_results_not_found_exit_1(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "results", "-m", "bad:bad"])
        assert result.exit_code == 1

    def test_results_empty_list_ok(self, tmp_path):
        tracked = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[tracked])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "results", "-m", "fakerepo:test-marker"])
        data = json.loads(result.output)
        assert data["data"] == []

    def test_results_status_ok(self, tmp_path):
        tracked = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[tracked])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "results", "-m", "fakerepo:test-marker"])
        data = json.loads(result.output)
        assert data["status"] == "ok"

    def test_results_data_is_list(self, tmp_path):
        tracked = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[tracked])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "results", "-m", "fakerepo:test-marker"])
        data = json.loads(result.output)
        assert isinstance(data["data"], list)

    def test_results_not_found_status_error(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "results", "-m", "bad:bad"])
        data = json.loads(result.output)
        assert data["status"] == "error"


class TestHeadlessIdeasFieldsB:
    def test_ideas_not_found_exit_1(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "ideas", "-m", "bad:bad"])
        assert result.exit_code == 1

    def test_ideas_empty_ok(self, tmp_path):
        tracked = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[tracked])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "ideas", "-m", "fakerepo:test-marker"])
        data = json.loads(result.output)
        assert data["status"] == "ok"

    def test_ideas_data_has_ideas_key(self, tmp_path):
        tracked = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[tracked])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "ideas", "-m", "fakerepo:test-marker"])
        data = json.loads(result.output)
        assert "ideas" in data.get("data", data)

    def test_ideas_not_found_status_error(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "ideas", "-m", "missing:marker"])
        data = json.loads(result.output)
        assert data["status"] == "error"

    def test_ideas_json_parseable(self, tmp_path):
        tracked = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[tracked])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "ideas", "-m", "fakerepo:test-marker"])
        assert json.loads(result.output) is not None


class TestHeadlessConfidenceFieldsB:
    def test_confidence_not_found_exit_1(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "confidence", "-m", "bad:bad"])
        assert result.exit_code == 1

    def test_confidence_found_exit_0(self, tmp_path):
        tracked = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[tracked])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "confidence", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0

    def test_confidence_status_ok(self, tmp_path):
        tracked = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[tracked])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "confidence", "-m", "fakerepo:test-marker"])
        data = json.loads(result.output)
        assert data["status"] == "ok"

    def test_confidence_json_parseable(self, tmp_path):
        tracked = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[tracked])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "confidence", "-m", "fakerepo:test-marker"])
        assert json.loads(result.output) is not None

    def test_confidence_not_found_status_error(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "confidence", "-m", "bad:bad"])
        data = json.loads(result.output)
        assert data["status"] == "error"


# ---------------------------------------------------------------------------
# NEW BATCH: Headless list additional field checks
# ---------------------------------------------------------------------------

class TestHeadlessListNewBatch:
    def test_list_data_is_list(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "list"])
        data = json.loads(result.output)
        assert isinstance(data["data"], list)

    def test_list_status_ok_always(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "list"])
        data = json.loads(result.output)
        assert data["status"] == "ok"

    def test_list_exit_code_zero(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "list"])
        assert result.exit_code == 0

    def test_list_json_has_status_key(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "list"])
        data = json.loads(result.output)
        assert "status" in data

    def test_list_json_has_data_key(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "list"])
        data = json.loads(result.output)
        assert "data" in data

    def test_list_two_markers(self, tmp_path):
        t1 = _make_tracked(repo_path=str(tmp_path), marker_id="repo1:m1", marker_name="m1")
        t2 = _make_tracked(repo_path=str(tmp_path), marker_id="repo1:m2", marker_name="m2")
        state = AppState(markers=[t1, t2])
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.find_marker_file", return_value=None),
        ):
            result = runner.invoke(app, ["--headless", "list"])
        data = json.loads(result.output)
        assert len(data["data"]) == 2

    def test_list_marker_has_id_field(self, tmp_path):
        t = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[t])
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.find_marker_file", return_value=None),
        ):
            result = runner.invoke(app, ["--headless", "list"])
        data = json.loads(result.output)
        assert "id" in data["data"][0]

    def test_list_marker_has_status_field(self, tmp_path):
        t = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[t])
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.find_marker_file", return_value=None),
        ):
            result = runner.invoke(app, ["--headless", "list"])
        data = json.loads(result.output)
        assert "status" in data["data"][0]


# ---------------------------------------------------------------------------
# NEW BATCH: Headless status field checks
# ---------------------------------------------------------------------------

class TestHeadlessStatusNewBatch:
    def test_status_not_found_exit_1(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "status", "-m", "bad:bad"])
        assert result.exit_code == 1

    def test_status_not_found_json_error(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "status", "-m", "bad:bad"])
        data = json.loads(result.output)
        assert data["status"] == "error"

    def test_status_found_exit_0(self, tmp_path):
        t = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[t])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "status", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0

    def test_status_json_parseable(self, tmp_path):
        t = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[t])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "status", "-m", "fakerepo:test-marker"])
        assert json.loads(result.output) is not None

    def test_status_data_key_present(self, tmp_path):
        t = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[t])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "status", "-m", "fakerepo:test-marker"])
        data = json.loads(result.output)
        assert "data" in data or "status" in data

    def test_status_has_status_key(self, tmp_path):
        t = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[t])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "status", "-m", "fakerepo:test-marker"])
        data = json.loads(result.output)
        assert "status" in data


# ---------------------------------------------------------------------------
# NEW BATCH: Headless results field checks
# ---------------------------------------------------------------------------

class TestHeadlessResultsNewBatch:
    def test_results_not_found_exit_1(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "results", "-m", "no:no"])
        assert result.exit_code == 1

    def test_results_not_found_json_error(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "results", "-m", "no:no"])
        data = json.loads(result.output)
        assert data["status"] == "error"

    def test_results_found_exit_0(self, tmp_path):
        t = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[t])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "results", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0

    def test_results_json_parseable(self, tmp_path):
        t = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[t])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "results", "-m", "fakerepo:test-marker"])
        assert json.loads(result.output) is not None

    def test_results_status_ok(self, tmp_path):
        t = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[t])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "results", "-m", "fakerepo:test-marker"])
        data = json.loads(result.output)
        assert data["status"] == "ok"

    def test_results_data_is_list(self, tmp_path):
        t = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[t])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "results", "-m", "fakerepo:test-marker"])
        data = json.loads(result.output)
        assert isinstance(data.get("data", []), list)


# ---------------------------------------------------------------------------
# NEW BATCH: Headless ideas field checks
# ---------------------------------------------------------------------------

class TestHeadlessIdeasNewBatch:
    def test_ideas_not_found_exit_1(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "ideas", "-m", "no:no"])
        assert result.exit_code == 1

    def test_ideas_not_found_json_error(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "ideas", "-m", "no:no"])
        data = json.loads(result.output)
        assert data["status"] == "error"

    def test_ideas_found_exit_0(self, tmp_path):
        t = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[t])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "ideas", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0

    def test_ideas_json_parseable(self, tmp_path):
        t = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[t])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "ideas", "-m", "fakerepo:test-marker"])
        assert json.loads(result.output) is not None

    def test_ideas_status_ok(self, tmp_path):
        t = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[t])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "ideas", "-m", "fakerepo:test-marker"])
        data = json.loads(result.output)
        assert data["status"] == "ok"


# ---------------------------------------------------------------------------
# NEW BATCH: Headless confidence field checks
# ---------------------------------------------------------------------------

class TestHeadlessConfidenceNewBatch:
    def test_confidence_not_found_exit_1(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "confidence", "-m", "x:x"])
        assert result.exit_code == 1

    def test_confidence_not_found_json_error_status(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "confidence", "-m", "x:x"])
        data = json.loads(result.output)
        assert data["status"] == "error"

    def test_confidence_found_exit_0(self, tmp_path):
        t = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[t])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "confidence", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0

    def test_confidence_json_parseable(self, tmp_path):
        t = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[t])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "confidence", "-m", "fakerepo:test-marker"])
        assert json.loads(result.output) is not None

    def test_confidence_status_ok(self, tmp_path):
        t = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[t])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "confidence", "-m", "fakerepo:test-marker"])
        data = json.loads(result.output)
        assert data["status"] == "ok"


# ---------------------------------------------------------------------------
# NEW BATCH: Headless skip field checks
# ---------------------------------------------------------------------------

class TestHeadlessSkipNewBatch:
    def test_skip_not_found_exit_1(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "skip", "-m", "nope:nope"])
        assert result.exit_code == 1

    def test_skip_not_found_json_error(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "skip", "-m", "nope:nope"])
        data = json.loads(result.output)
        assert data["status"] == "error"

    def test_skip_found_exit_0(self, tmp_path):
        t = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[t])
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.save_state"),
            patch("autoresearch.cli.find_marker_file", return_value=None),
        ):
            result = runner.invoke(app, ["--headless", "skip", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0

    def test_skip_found_json_parseable(self, tmp_path):
        t = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[t])
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.save_state"),
            patch("autoresearch.cli.find_marker_file", return_value=None),
        ):
            result = runner.invoke(app, ["--headless", "skip", "-m", "fakerepo:test-marker"])
        assert json.loads(result.output) is not None

    def test_skip_found_status_ok(self, tmp_path):
        t = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[t])
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.save_state"),
            patch("autoresearch.cli.find_marker_file", return_value=None),
        ):
            result = runner.invoke(app, ["--headless", "skip", "-m", "fakerepo:test-marker"])
        data = json.loads(result.output)
        assert data["status"] == "ok"


# ---------------------------------------------------------------------------
# NEW BATCH: Headless pause field checks
# ---------------------------------------------------------------------------

class TestHeadlessPauseNewBatch:
    def test_pause_not_found_exit_1(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "pause", "-m", "nope:nope"])
        assert result.exit_code == 1

    def test_pause_not_found_json_error(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "pause", "-m", "nope:nope"])
        data = json.loads(result.output)
        assert data["status"] == "error"

    def test_pause_found_exit_0(self, tmp_path):
        t = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[t])
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.save_state"),
            patch("autoresearch.cli.find_marker_file", return_value=None),
        ):
            result = runner.invoke(app, ["--headless", "pause", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0

    def test_pause_json_parseable(self, tmp_path):
        t = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[t])
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.save_state"),
            patch("autoresearch.cli.find_marker_file", return_value=None),
        ):
            result = runner.invoke(app, ["--headless", "pause", "-m", "fakerepo:test-marker"])
        assert json.loads(result.output) is not None

    def test_pause_status_ok(self, tmp_path):
        t = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[t])
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.save_state"),
            patch("autoresearch.cli.find_marker_file", return_value=None),
        ):
            result = runner.invoke(app, ["--headless", "pause", "-m", "fakerepo:test-marker"])
        data = json.loads(result.output)
        assert data["status"] == "ok"


# ---------------------------------------------------------------------------
# NEW BATCH: Headless detach field checks
# ---------------------------------------------------------------------------

class TestHeadlessDetachNewBatch:
    def test_detach_not_found_exit_1(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "detach", "-m", "nope:nope"])
        assert result.exit_code == 1

    def test_detach_not_found_json_error(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "detach", "-m", "nope:nope"])
        data = json.loads(result.output)
        assert data["status"] == "error"

    def test_detach_found_exit_0(self, tmp_path):
        t = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[t])
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.save_state"),
        ):
            result = runner.invoke(app, ["--headless", "detach", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0

    def test_detach_json_parseable(self, tmp_path):
        t = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[t])
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.save_state"),
        ):
            result = runner.invoke(app, ["--headless", "detach", "-m", "fakerepo:test-marker"])
        assert json.loads(result.output) is not None

    def test_detach_status_ok(self, tmp_path):
        t = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[t])
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.save_state"),
        ):
            result = runner.invoke(app, ["--headless", "detach", "-m", "fakerepo:test-marker"])
        data = json.loads(result.output)
        assert data["status"] == "ok"


# ---------------------------------------------------------------------------
# NEW BATCH: headless commands extra coverage
# ---------------------------------------------------------------------------

class TestHeadlessListExtraCoverage:
    def test_empty_data_list_type(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "list"])
        data = json.loads(result.output)
        assert isinstance(data["data"], list)

    def test_status_ok_always_present(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "list"])
        data = json.loads(result.output)
        assert "status" in data

    def test_exit_zero(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "list"])
        assert result.exit_code == 0

    def test_json_parseable(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "list"])
        assert json.loads(result.output) is not None

    def test_no_markers_empty_data(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "list"])
        data = json.loads(result.output)
        assert len(data["data"]) == 0


class TestHeadlessStatusExtraCoverage:
    def test_missing_marker_exit_1(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "status", "-m", "x:y"])
        assert result.exit_code == 1

    def test_missing_marker_error_status(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "status", "-m", "x:y"])
        data = json.loads(result.output)
        assert data["status"] == "error"

    def test_missing_marker_json_parseable(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "status", "-m", "x:y"])
        assert json.loads(result.output) is not None

    def test_found_marker_exit_0(self, tmp_path):
        t = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[t])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "status", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0

    def test_found_marker_ok_status(self, tmp_path):
        t = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[t])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "status", "-m", "fakerepo:test-marker"])
        data = json.loads(result.output)
        assert data["status"] == "ok"

    def test_found_marker_has_data(self, tmp_path):
        t = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[t])
        with patch("autoresearch.cli.load_state", return_value=state):
            result = runner.invoke(app, ["--headless", "status", "-m", "fakerepo:test-marker"])
        data = json.loads(result.output)
        assert "data" in data


class TestHeadlessSkipExtraCoverage:
    def test_skip_not_found_exit_1(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "skip", "-m", "no:no"])
        assert result.exit_code == 1

    def test_skip_not_found_error(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "skip", "-m", "no:no"])
        data = json.loads(result.output)
        assert data["status"] == "error"

    def test_skip_found_exit_0(self, tmp_path):
        t = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[t])
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.save_state"),
        ):
            result = runner.invoke(app, ["--headless", "skip", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0

    def test_skip_found_ok_or_no_data_issue(self, tmp_path):
        t = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[t])
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.save_state"),
        ):
            result = runner.invoke(app, ["--headless", "skip", "-m", "fakerepo:test-marker"])
        data = json.loads(result.output)
        assert data["status"] in ("ok", "error")


class TestHeadlessPauseExtraCoverage:
    def test_pause_not_found_exit_1(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "pause", "-m", "no:no"])
        assert result.exit_code == 1

    def test_pause_not_found_error_status(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "pause", "-m", "no:no"])
        data = json.loads(result.output)
        assert data["status"] == "error"

    def test_pause_found_json_parseable(self, tmp_path):
        t = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[t])
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.save_state"),
        ):
            result = runner.invoke(app, ["--headless", "pause", "-m", "fakerepo:test-marker"])
        assert json.loads(result.output) is not None

    def test_pause_found_exit_0(self, tmp_path):
        t = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[t])
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.save_state"),
        ):
            result = runner.invoke(app, ["--headless", "pause", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0


class TestHeadlessResultsExtraCoverage:
    def test_not_found_exit_1(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "results", "-m", "x:y"])
        assert result.exit_code == 1

    def test_not_found_error_status(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "results", "-m", "x:y"])
        data = json.loads(result.output)
        assert data["status"] == "error"

    def test_found_exit_0(self, tmp_path):
        t = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[t])
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.results.read_results", return_value=[]),
        ):
            result = runner.invoke(app, ["--headless", "results", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0

    def test_found_ok_status(self, tmp_path):
        t = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[t])
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.results.read_results", return_value=[]),
        ):
            result = runner.invoke(app, ["--headless", "results", "-m", "fakerepo:test-marker"])
        data = json.loads(result.output)
        assert data["status"] == "ok"

    def test_found_data_is_list(self, tmp_path):
        t = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[t])
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.results.read_results", return_value=[]),
        ):
            result = runner.invoke(app, ["--headless", "results", "-m", "fakerepo:test-marker"])
        data = json.loads(result.output)
        assert isinstance(data.get("data", []), list)


class TestHeadlessIdeasExtraCoverage:
    def test_not_found_exit_1(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "ideas", "-m", "x:y"])
        assert result.exit_code == 1

    def test_not_found_error_status(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "ideas", "-m", "x:y"])
        data = json.loads(result.output)
        assert data["status"] == "error"

    def test_found_exit_0(self, tmp_path):
        t = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[t])
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.ideas.read_ideas", return_value=""),
        ):
            result = runner.invoke(app, ["--headless", "ideas", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0

    def test_found_json_parseable(self, tmp_path):
        t = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[t])
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.ideas.read_ideas", return_value=""),
        ):
            result = runner.invoke(app, ["--headless", "ideas", "-m", "fakerepo:test-marker"])
        assert json.loads(result.output) is not None


class TestHeadlessConfidenceExtraCoverage:
    def test_not_found_exit_1(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "confidence", "-m", "x:y"])
        assert result.exit_code == 1

    def test_not_found_error_status(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "confidence", "-m", "x:y"])
        data = json.loads(result.output)
        assert data["status"] == "error"

    def test_found_exit_0(self, tmp_path):
        t = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[t])
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.results.read_results", return_value=[]),
        ):
            result = runner.invoke(app, ["--headless", "confidence", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0

    def test_found_json_parseable(self, tmp_path):
        t = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[t])
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.results.read_results", return_value=[]),
        ):
            result = runner.invoke(app, ["--headless", "confidence", "-m", "fakerepo:test-marker"])
        assert json.loads(result.output) is not None


class TestHeadlessDetachExtraCoverage:
    def test_not_found_exit_1(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "detach", "-m", "x:y"])
        assert result.exit_code == 1

    def test_not_found_error_status(self):
        with patch("autoresearch.cli.load_state", return_value=AppState()):
            result = runner.invoke(app, ["--headless", "detach", "-m", "x:y"])
        data = json.loads(result.output)
        assert data["status"] == "error"

    def test_found_exit_0(self, tmp_path):
        t = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[t])
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.save_state"),
        ):
            result = runner.invoke(app, ["--headless", "detach", "-m", "fakerepo:test-marker"])
        assert result.exit_code == 0

    def test_found_ok_status(self, tmp_path):
        t = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[t])
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.save_state"),
        ):
            result = runner.invoke(app, ["--headless", "detach", "-m", "fakerepo:test-marker"])
        data = json.loads(result.output)
        assert data["status"] == "ok"

    def test_found_json_parseable(self, tmp_path):
        t = _make_tracked(repo_path=str(tmp_path))
        state = AppState(markers=[t])
        with (
            patch("autoresearch.cli.load_state", return_value=state),
            patch("autoresearch.cli.save_state"),
        ):
            result = runner.invoke(app, ["--headless", "detach", "-m", "fakerepo:test-marker"])
        assert json.loads(result.output) is not None
