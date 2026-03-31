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


# ---------------------------------------------------------------------------
# Additional branch coverage
# ---------------------------------------------------------------------------


class TestIsPidAlivePermissionError:
    def test_permission_error_returns_true(self):
        """PermissionError means the process exists but is owned by another user."""
        with patch("os.kill", side_effect=PermissionError):
            assert is_pid_alive(12345) is True


class TestIsDueNaiveDatetime:
    def test_naive_last_run_treated_as_utc(self):
        """Naive ISO strings (no tzinfo) should be treated as UTC."""
        # 3 hours ago naive → should be due for hourly cron
        naive_dt = (datetime.now(timezone.utc) - timedelta(hours=3)).replace(tzinfo=None)
        last_run = naive_dt.isoformat()
        assert is_due(_make_schedule("cron", "0 * * * *"), last_run) is True


class TestDaemonRunnerRun:
    def test_run_calls_tick_then_joins(self):
        from autoresearch.config import GlobalConfig
        runner = DaemonRunner(config=GlobalConfig())

        tick_calls = []

        def fake_tick():
            tick_calls.append(1)
            runner.shutdown()  # Trigger exit after first tick

        runner._tick = fake_tick

        with patch.object(runner, "_join_threads") as mock_join:
            runner.run()

        assert len(tick_calls) == 1
        mock_join.assert_called_once()

    def test_run_catches_tick_exception(self):
        from autoresearch.config import GlobalConfig
        runner = DaemonRunner(config=GlobalConfig())

        call_count = [0]

        def exploding_tick():
            call_count[0] += 1
            runner.shutdown()
            raise RuntimeError("boom")

        runner._tick = exploding_tick

        # Should not raise
        runner.run()
        assert call_count[0] == 1


class TestDaemonRunnerTickBranches:
    def _make_runner(self):
        from autoresearch.config import GlobalConfig
        return DaemonRunner(config=GlobalConfig())

    def test_no_marker_file_skips(self):
        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        runner = self._make_runner()

        with (
            patch("autoresearch.daemon.load_state", return_value=state),
            patch("autoresearch.daemon.find_marker_file", return_value=None),
        ):
            runner._tick()
        assert len(runner._active_runs) == 0

    def test_load_markers_error_skips(self):
        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        runner = self._make_runner()

        with (
            patch("autoresearch.daemon.load_state", return_value=state),
            patch("autoresearch.daemon.find_marker_file", return_value=Path("/tmp/fake.yaml")),
            patch("autoresearch.daemon.load_markers", side_effect=ValueError("bad yaml")),
        ):
            runner._tick()
        assert len(runner._active_runs) == 0

    def test_marker_not_found_skips(self):
        tracked = _make_tracked()
        state = AppState(markers=[tracked])
        runner = self._make_runner()
        mf = MagicMock()

        with (
            patch("autoresearch.daemon.load_state", return_value=state),
            patch("autoresearch.daemon.find_marker_file", return_value=Path("/tmp/fake.yaml")),
            patch("autoresearch.daemon.load_markers", return_value=mf),
            patch("autoresearch.daemon.get_marker", return_value=None),
        ):
            runner._tick()
        assert len(runner._active_runs) == 0


class TestDaemonRunnerThread:
    def _make_runner(self):
        from autoresearch.config import GlobalConfig
        return DaemonRunner(config=GlobalConfig())

    def test_run_marker_thread_success(self):
        tracked = _make_tracked()
        marker = _make_marker()
        state = AppState(markers=[tracked])
        runner = self._make_runner()
        mock_result = MagicMock(experiments=1, kept=1)
        runner._semaphore.acquire()  # Simulate semaphore acquired before thread starts

        with (
            patch("autoresearch.daemon.load_state", return_value=state),
            patch("autoresearch.daemon.get_tracked", return_value=tracked),
            patch("autoresearch.daemon.get_agent_runner", return_value=MagicMock()),
            patch("autoresearch.daemon.run_marker", return_value=mock_result),
        ):
            runner._run_marker_thread(tracked, marker)
        # Semaphore should have been released (value back to initial)
        assert runner._semaphore._value == runner._config.daemon.max_concurrent

    def test_run_marker_thread_tracked_not_found(self):
        tracked = _make_tracked()
        marker = _make_marker()
        state = AppState(markers=[tracked])
        runner = self._make_runner()
        runner._semaphore.acquire()

        with (
            patch("autoresearch.daemon.load_state", return_value=state),
            patch("autoresearch.daemon.get_tracked", return_value=None),
        ):
            runner._run_marker_thread(tracked, marker)
        # No crash, semaphore released
        assert runner._semaphore._value == runner._config.daemon.max_concurrent

    def test_run_marker_thread_engine_error(self):
        from autoresearch.engine import EngineError
        tracked = _make_tracked()
        marker = _make_marker()
        state = AppState(markers=[tracked])
        runner = self._make_runner()
        runner._semaphore.acquire()

        with (
            patch("autoresearch.daemon.load_state", return_value=state),
            patch("autoresearch.daemon.get_tracked", return_value=tracked),
            patch("autoresearch.daemon.get_agent_runner", return_value=MagicMock()),
            patch("autoresearch.daemon.run_marker", side_effect=EngineError("engine fail")),
        ):
            runner._run_marker_thread(tracked, marker)
        assert runner._semaphore._value == runner._config.daemon.max_concurrent

    def test_run_marker_thread_unexpected_exception(self):
        tracked = _make_tracked()
        marker = _make_marker()
        state = AppState(markers=[tracked])
        runner = self._make_runner()
        runner._semaphore.acquire()

        with (
            patch("autoresearch.daemon.load_state", return_value=state),
            patch("autoresearch.daemon.get_tracked", return_value=tracked),
            patch("autoresearch.daemon.get_agent_runner", return_value=MagicMock()),
            patch("autoresearch.daemon.run_marker", side_effect=RuntimeError("unexpected")),
        ):
            runner._run_marker_thread(tracked, marker)
        assert runner._semaphore._value == runner._config.daemon.max_concurrent


class TestDaemonRunnerJoinThreads:
    def test_join_threads_waits(self):
        from autoresearch.config import GlobalConfig
        runner = DaemonRunner(config=GlobalConfig())

        mock_thread = MagicMock()
        runner._active_runs = {"m1": mock_thread}
        runner._join_threads(timeout=1.0)

        mock_thread.join.assert_called_once_with(timeout=1.0)

    def test_join_threads_multiple(self):
        from autoresearch.config import GlobalConfig
        runner = DaemonRunner(config=GlobalConfig())

        t1 = MagicMock()
        t2 = MagicMock()
        runner._active_runs = {"m1": t1, "m2": t2}
        runner._join_threads(timeout=2.0)

        t1.join.assert_called_once_with(timeout=2.0)
        t2.join.assert_called_once_with(timeout=2.0)

    def test_join_threads_empty(self):
        from autoresearch.config import GlobalConfig
        runner = DaemonRunner(config=GlobalConfig())
        runner._active_runs = {}
        # Should not raise
        runner._join_threads(timeout=1.0)


class TestDaemonRunnerReapThreads:
    def test_removes_dead_threads(self):
        from autoresearch.config import GlobalConfig
        runner = DaemonRunner(config=GlobalConfig())

        alive = MagicMock()
        alive.is_alive.return_value = True
        dead = MagicMock()
        dead.is_alive.return_value = False
        runner._active_runs = {"alive": alive, "dead": dead}
        runner._reap_threads()

        assert "alive" in runner._active_runs
        assert "dead" not in runner._active_runs

    def test_keeps_all_when_alive(self):
        from autoresearch.config import GlobalConfig
        runner = DaemonRunner(config=GlobalConfig())

        t1 = MagicMock()
        t1.is_alive.return_value = True
        t2 = MagicMock()
        t2.is_alive.return_value = True
        runner._active_runs = {"m1": t1, "m2": t2}
        runner._reap_threads()

        assert len(runner._active_runs) == 2

    def test_removes_all_when_dead(self):
        from autoresearch.config import GlobalConfig
        runner = DaemonRunner(config=GlobalConfig())

        t1 = MagicMock()
        t1.is_alive.return_value = False
        t2 = MagicMock()
        t2.is_alive.return_value = False
        runner._active_runs = {"m1": t1, "m2": t2}
        runner._reap_threads()

        assert len(runner._active_runs) == 0


class TestDaemonRunnerShutdown:
    def test_shutdown_sets_event(self):
        from autoresearch.config import GlobalConfig
        runner = DaemonRunner(config=GlobalConfig())
        assert not runner._shutdown.is_set()
        runner.shutdown()
        assert runner._shutdown.is_set()


class TestStopDaemonPidDiesAfterCheck:
    def test_pid_alive_at_check_dead_at_kill_returns_false(self, tmp_path):
        """Lines 343-345: pid present but dies between check_stale_pid and is_pid_alive call."""
        pid_path = tmp_path / "test.pid"
        write_pid(12345, pid_path)
        # First call (in check_stale_pid): alive → don't clear
        # Second call (in stop_daemon body): dead → clear and return False
        with patch("autoresearch.daemon.is_pid_alive", side_effect=[True, False]):
            result = stop_daemon(pid_path=pid_path)
        assert result is False
        # pid file should be cleared
        assert read_pid(pid_path) is None
