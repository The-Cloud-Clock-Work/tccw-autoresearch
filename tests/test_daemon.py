"""Tests for daemon module."""

from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from autoresearch.daemon import (
    DaemonRunner,
    _resolve_cron_expression,
    check_stale_pid,
    clear_pid,
    is_due,
    is_pid_alive,
    read_pid,
    stop_daemon,
    write_pid,
)
from autoresearch.marker import (
    Marker,
    MarkerFile,
    MarkerStatus,
    Metric,
    Schedule,
    Target,
    LoopConfig,
)
from autoresearch.state import AppState, TrackedMarker


def _make_schedule(type: str = "on-demand", cron: str | None = None) -> Schedule:
    return Schedule(type=type, cron=cron)


def _make_marker(name="test", schedule_type="on-demand", cron=None) -> Marker:
    return Marker(
        name=name,
        target=Target(mutable=["src/main.py"]),
        metric=Metric(command="echo 1", extract=r"\d+", direction="higher", baseline=1.0),
        loop=LoopConfig(model="sonnet", budget_per_experiment="5m", max_experiments=10),
        schedule=Schedule(type=schedule_type, cron=cron),
    )


def _make_tracked(marker_name="test", last_run=None, **kwargs) -> TrackedMarker:
    return TrackedMarker(
        id=f"repo:{marker_name}",
        repo_path="/tmp/fakerepo",
        repo_name="repo",
        marker_name=marker_name,
        last_run=last_run,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Schedule evaluation
# ---------------------------------------------------------------------------

class TestResolveCronExpression:
    def test_on_demand_returns_none(self):
        assert _resolve_cron_expression(_make_schedule("on-demand")) is None

    def test_cron_with_expression(self):
        assert _resolve_cron_expression(_make_schedule("cron", "0 1 * * *")) == "0 1 * * *"

    def test_cron_without_expression(self):
        assert _resolve_cron_expression(_make_schedule("cron")) is None

    def test_overnight(self):
        assert _resolve_cron_expression(_make_schedule("overnight")) == "0 1 * * *"

    def test_weekend(self):
        assert _resolve_cron_expression(_make_schedule("weekend")) == "0 1 * * 6"

    def test_unknown_type(self):
        assert _resolve_cron_expression(_make_schedule("custom")) is None


class TestIsDue:
    def test_on_demand_never_due(self):
        assert is_due(_make_schedule("on-demand"), None) is False

    def test_first_run_always_due(self):
        assert is_due(_make_schedule("cron", "0 * * * *"), None) is True

    def test_cron_due(self):
        # Last run was 2 hours ago, cron fires every hour
        last = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        assert is_due(_make_schedule("cron", "0 * * * *"), last) is True

    def test_cron_not_due(self):
        # Last run was 5 seconds ago, cron fires every hour
        last = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
        assert is_due(_make_schedule("cron", "0 * * * *"), last) is False

    def test_overnight_due_next_day(self):
        # Last run was yesterday at 01:00, now is today at 02:00
        yesterday_1am = datetime(2026, 3, 29, 1, 0, tzinfo=timezone.utc)
        today_2am = datetime(2026, 3, 30, 2, 0, tzinfo=timezone.utc)
        assert is_due(_make_schedule("overnight"), yesterday_1am.isoformat(), now=today_2am) is True

    def test_overnight_not_due_same_day(self):
        # Last run was today at 01:00, now is today at 02:00
        today_1am = datetime(2026, 3, 30, 1, 0, tzinfo=timezone.utc)
        today_2am = datetime(2026, 3, 30, 2, 0, tzinfo=timezone.utc)
        assert is_due(_make_schedule("overnight"), today_1am.isoformat(), now=today_2am) is False

    def test_invalid_last_run_is_due(self):
        assert is_due(_make_schedule("cron", "0 * * * *"), "not-a-date") is True

    def test_invalid_cron_not_due(self):
        assert is_due(_make_schedule("cron", "invalid cron"), "2026-03-30T01:00:00+00:00") is False


# ---------------------------------------------------------------------------
# PID management
# ---------------------------------------------------------------------------

class TestPidManagement:
    def test_write_read_roundtrip(self, tmp_path):
        pid_path = tmp_path / "test.pid"
        write_pid(12345, pid_path)
        assert read_pid(pid_path) == 12345

    def test_read_missing_returns_none(self, tmp_path):
        assert read_pid(tmp_path / "missing.pid") is None

    def test_read_corrupt_returns_none(self, tmp_path):
        pid_path = tmp_path / "bad.pid"
        pid_path.write_text("not-a-number")
        assert read_pid(pid_path) is None

    def test_clear_pid(self, tmp_path):
        pid_path = tmp_path / "test.pid"
        write_pid(123, pid_path)
        clear_pid(pid_path)
        assert not pid_path.exists()

    def test_clear_missing_ok(self, tmp_path):
        clear_pid(tmp_path / "missing.pid")  # Should not raise

    def test_is_pid_alive_current_process(self):
        assert is_pid_alive(os.getpid()) is True

    def test_is_pid_alive_dead(self):
        assert is_pid_alive(99999999) is False

    def test_check_stale_cleans_up(self, tmp_path):
        pid_path = tmp_path / "test.pid"
        write_pid(99999999, pid_path)  # Nonexistent PID
        assert check_stale_pid(pid_path) is True
        assert not pid_path.exists()

    def test_check_stale_live_noop(self, tmp_path):
        pid_path = tmp_path / "test.pid"
        write_pid(os.getpid(), pid_path)
        assert check_stale_pid(pid_path) is False
        assert pid_path.exists()

    def test_check_stale_no_file(self, tmp_path):
        assert check_stale_pid(tmp_path / "missing.pid") is False




# ---------------------------------------------------------------------------
# DaemonRunner
# ---------------------------------------------------------------------------

class TestDaemonRunnerTick:
    def _make_runner(self, config=None):
        from autoresearch.config import GlobalConfig
        cfg = config or GlobalConfig()
        return DaemonRunner(config=cfg)

    def test_no_markers_no_threads(self):
        runner = self._make_runner()
        with patch("autoresearch.daemon.load_state", return_value=AppState()):
            runner._tick()
        assert len(runner._active_runs) == 0

    def test_on_demand_skipped(self):
        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        marker = _make_marker(schedule_type="on-demand")
        mf = MarkerFile(markers=[marker])

        runner = self._make_runner()
        with (
            patch("autoresearch.daemon.load_state", return_value=state),
            patch("autoresearch.daemon.find_marker_file", return_value=Path("/tmp/.autoresearch.yaml")),
            patch("autoresearch.daemon.load_markers", return_value=mf),
        ):
            runner._tick()
        assert len(runner._active_runs) == 0

    def test_due_cron_marker_spawns_thread(self):
        tracked = _make_tracked(last_run=None)  # Never run = immediately due
        state = AppState(markers=[tracked])
        marker = _make_marker(schedule_type="cron", cron="0 * * * *")
        mf = MarkerFile(markers=[marker])

        runner = self._make_runner()
        with (
            patch("autoresearch.daemon.load_state", return_value=state),
            patch("autoresearch.daemon.find_marker_file", return_value=Path("/tmp/.autoresearch.yaml")),
            patch("autoresearch.daemon.load_markers", return_value=mf),
            patch("autoresearch.daemon.get_effective_status", return_value=MarkerStatus.ACTIVE),
            patch.object(runner, "_run_marker_thread"),  # Don't actually run
        ):
            runner._tick()
        assert "repo:test" in runner._active_runs

    def test_non_active_skipped(self):
        tracked = _make_tracked(last_run=None)
        state = AppState(markers=[tracked])
        marker = _make_marker(schedule_type="cron", cron="0 * * * *")
        marker.status = MarkerStatus.SKIP
        mf = MarkerFile(markers=[marker])

        runner = self._make_runner()
        with (
            patch("autoresearch.daemon.load_state", return_value=state),
            patch("autoresearch.daemon.find_marker_file", return_value=Path("/tmp/.autoresearch.yaml")),
            patch("autoresearch.daemon.load_markers", return_value=mf),
            patch("autoresearch.daemon.get_effective_status", return_value=MarkerStatus.SKIP),
        ):
            runner._tick()
        assert len(runner._active_runs) == 0

    def test_already_running_skipped(self):
        tracked = _make_tracked(last_run=None)
        state = AppState(markers=[tracked])
        marker = _make_marker(schedule_type="cron", cron="0 * * * *")
        mf = MarkerFile(markers=[marker])

        runner = self._make_runner()
        runner._active_runs["repo:test"] = MagicMock()  # Simulate running

        with (
            patch("autoresearch.daemon.load_state", return_value=state),
            patch("autoresearch.daemon.find_marker_file", return_value=Path("/tmp/.autoresearch.yaml")),
            patch("autoresearch.daemon.load_markers", return_value=mf),
        ):
            runner._tick()
        # No new thread spawned, still just the mock
        assert len(runner._active_runs) == 1

    def test_max_concurrent_defers(self):
        from autoresearch.config import DaemonConfig, GlobalConfig

        cfg = GlobalConfig(daemon=DaemonConfig(max_concurrent=1))
        runner = self._make_runner(config=cfg)

        # Exhaust the semaphore
        runner._semaphore.acquire(blocking=False)

        tracked = _make_tracked(last_run=None)
        state = AppState(markers=[tracked])
        marker = _make_marker(schedule_type="cron", cron="0 * * * *")
        mf = MarkerFile(markers=[marker])

        with (
            patch("autoresearch.daemon.load_state", return_value=state),
            patch("autoresearch.daemon.find_marker_file", return_value=Path("/tmp/.autoresearch.yaml")),
            patch("autoresearch.daemon.load_markers", return_value=mf),
            patch("autoresearch.daemon.get_effective_status", return_value=MarkerStatus.ACTIVE),
        ):
            runner._tick()
        assert len(runner._active_runs) == 0

        runner._semaphore.release()


class TestDaemonRunnerLifecycle:
    def test_shutdown_stops_loop(self):
        from autoresearch.config import GlobalConfig
        runner = DaemonRunner(config=GlobalConfig())
        runner.shutdown()
        assert runner._shutdown.is_set()

    def test_reap_threads(self):
        from autoresearch.config import GlobalConfig
        runner = DaemonRunner(config=GlobalConfig())

        mock_alive = MagicMock()
        mock_alive.is_alive.return_value = True
        mock_dead = MagicMock()
        mock_dead.is_alive.return_value = False

        runner._active_runs = {"alive": mock_alive, "dead": mock_dead}
        runner._reap_threads()

        assert "alive" in runner._active_runs
        assert "dead" not in runner._active_runs


# ---------------------------------------------------------------------------
# Stop daemon
# ---------------------------------------------------------------------------

class TestStopDaemon:
    def test_process_never_dies(self, tmp_path):
        """stop_daemon returns False if process doesn't terminate after SIGTERM."""
        pid_path = tmp_path / "test.pid"
        state_path = tmp_path / "state.json"
        write_pid(12345, pid_path)

        with (
            patch("autoresearch.daemon.is_pid_alive", return_value=True),  # Never dies
            patch("os.kill"),
            patch("autoresearch.daemon.time.sleep"),  # Don't actually wait
        ):
            result = stop_daemon(pid_path=pid_path, state_path=state_path)

        assert result is False  # Process still alive = not stopped

    def test_no_pid_file(self, tmp_path):
        assert stop_daemon(pid_path=tmp_path / "missing.pid") is False

    def test_stale_pid(self, tmp_path):
        pid_path = tmp_path / "test.pid"
        state_path = tmp_path / "state.json"
        write_pid(99999999, pid_path)  # Dead PID
        assert stop_daemon(pid_path=pid_path, state_path=state_path) is False

    def test_running_pid_sends_sigterm(self, tmp_path):
        pid_path = tmp_path / "test.pid"
        state_path = tmp_path / "state.json"
        write_pid(12345, pid_path)

        with (
            patch("autoresearch.daemon.is_pid_alive", side_effect=[True, True, False]),
            patch("os.kill") as mock_kill,
            patch("autoresearch.daemon.load_state", return_value=AppState()),
            patch("autoresearch.daemon.save_state"),
        ):
            result = stop_daemon(pid_path=pid_path, state_path=state_path)

        assert result is True
        mock_kill.assert_called_once_with(12345, 15)  # SIGTERM = 15
