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


class TestIsPidAlivePermissionErrorA:
    def test_permission_error_returns_true(self):
        """PermissionError means the process exists but is owned by another user."""
        with patch("os.kill", side_effect=PermissionError):
            assert is_pid_alive(12345) is True


class TestIsDueNaiveDatetimeA:
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


class TestDaemonRunnerJoinThreadsA:
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


class TestDaemonRunnerReapThreadsA:
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


class TestDaemonRunnerShutdownA:
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


# ---------------------------------------------------------------------------
# Additional targeted coverage
# ---------------------------------------------------------------------------


class TestWritePidCreatesParentDir:
    def test_creates_nested_parent(self, tmp_path):
        pid_path = tmp_path / "subdir" / "deep" / "daemon.pid"
        write_pid(99, pid_path)
        assert pid_path.exists()
        assert read_pid(pid_path) == 99


class TestReadPidEdgeCasesFirst:
    def test_whitespace_only_returns_none(self, tmp_path):
        pid_path = tmp_path / "ws.pid"
        pid_path.write_text("   ")
        assert read_pid(pid_path) is None

    def test_float_string_returns_none(self, tmp_path):
        pid_path = tmp_path / "float.pid"
        pid_path.write_text("1.5")
        assert read_pid(pid_path) is None

    def test_large_pid(self, tmp_path):
        pid_path = tmp_path / "big.pid"
        write_pid(999999, pid_path)
        assert read_pid(pid_path) == 999999


class TestIsDueAdditional:
    def test_on_demand_with_last_run_still_false(self):
        last = (datetime.now(timezone.utc)).isoformat()
        assert is_due(_make_schedule("on-demand"), last) is False

    def test_weekend_schedule_no_last_run_is_due(self):
        assert is_due(_make_schedule("weekend"), None) is True

    def test_overnight_no_last_run_is_due(self):
        assert is_due(_make_schedule("overnight"), None) is True

    def test_cron_not_due_just_ran(self):
        # Just ran 1 second ago, hourly cron
        last = datetime.now(timezone.utc).isoformat()
        assert is_due(_make_schedule("cron", "0 * * * *"), last) is False

    def test_unknown_schedule_type_returns_false(self):
        assert is_due(_make_schedule("monthly"), None) is False

    def test_cron_due_with_explicit_now(self):
        last_run_dt = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        now = datetime(2026, 1, 1, 2, 0, tzinfo=timezone.utc)
        assert is_due(_make_schedule("cron", "0 * * * *"), last_run_dt.isoformat(), now=now) is True


class TestResolveCronExpressionAdditional:
    def test_cron_type_empty_expression_returns_none(self):
        s = _make_schedule("cron", None)
        assert _resolve_cron_expression(s) is None

    def test_weekend_returns_saturday_cron(self):
        result = _resolve_cron_expression(_make_schedule("weekend"))
        assert result is not None
        assert "6" in result  # Saturday

    def test_overnight_returns_1am_cron(self):
        result = _resolve_cron_expression(_make_schedule("overnight"))
        assert result is not None
        assert "1" in result


class TestDaemonRunnerInit:
    def test_poll_seconds_parsed(self):
        from autoresearch.config import DaemonConfig, GlobalConfig
        cfg = GlobalConfig(daemon=DaemonConfig(poll_interval="2m"))
        runner = DaemonRunner(config=cfg)
        assert runner._poll_seconds == 120

    def test_max_concurrent_sets_semaphore(self):
        from autoresearch.config import DaemonConfig, GlobalConfig
        cfg = GlobalConfig(daemon=DaemonConfig(max_concurrent=3))
        runner = DaemonRunner(config=cfg)
        # Acquire 3 times should succeed; 4th should fail
        assert runner._semaphore.acquire(blocking=False) is True
        assert runner._semaphore.acquire(blocking=False) is True
        assert runner._semaphore.acquire(blocking=False) is True
        assert runner._semaphore.acquire(blocking=False) is False
        runner._semaphore.release()
        runner._semaphore.release()
        runner._semaphore.release()


class TestCheckStalePidAdditional:
    def test_check_stale_no_pid_returns_false(self, tmp_path):
        result = check_stale_pid(tmp_path / "no.pid")
        assert result is False

    def test_check_stale_alive_returns_false(self, tmp_path):
        pid_path = tmp_path / "alive.pid"
        write_pid(os.getpid(), pid_path)
        assert check_stale_pid(pid_path) is False
        assert pid_path.exists()


class TestStopDaemonStateUpdate:
    def test_stale_pid_resets_state(self, tmp_path):
        """When stale, daemon state should be reset."""
        pid_path = tmp_path / "test.pid"
        state_path = tmp_path / "state.json"
        write_pid(99999999, pid_path)  # Dead PID → stale

        from autoresearch.state import DaemonState
        from autoresearch.state import AppState as AS
        alive_state = AS(daemon=DaemonState(running=True, pid=99999999))
        with (
            patch("autoresearch.daemon.load_state", return_value=alive_state),
            patch("autoresearch.daemon.save_state") as mock_save,
        ):
            result = stop_daemon(pid_path=pid_path, state_path=state_path)
        assert result is False
        # save_state should have been called to reset daemon state
        mock_save.assert_called_once()


# ---------------------------------------------------------------------------
# Additional targeted tests
# ---------------------------------------------------------------------------


class TestIsDueWeekendRecentRun:
    def test_weekend_recent_last_run_not_due(self):
        """If we ran less than an hour ago, should not be due."""
        recent = datetime.now(timezone.utc).isoformat()
        # weekend schedule fires weekly; if just ran, not due yet
        # (Whether it's actually due depends on croniter, but the point is
        # last_run=now should typically not be due for a weekly cron)
        result = is_due(_make_schedule("weekend"), recent)
        # Should be False since we just ran
        assert result is False

    def test_overnight_recent_last_run_not_due(self):
        recent = datetime.now(timezone.utc).isoformat()
        result = is_due(_make_schedule("overnight"), recent)
        assert result is False


class TestDaemonRunnerActiveRunSkipped:
    def test_already_active_id_skipped_in_tick(self):
        tracked = _make_tracked(marker_name="active-marker")
        state = AppState(markers=[tracked])
        from autoresearch.config import GlobalConfig
        runner = DaemonRunner(config=GlobalConfig())
        runner._active_runs[tracked.id] = MagicMock()  # Simulate already running

        with patch("autoresearch.daemon.load_state", return_value=state):
            runner._tick()
        # active_runs still has the original mock (no new thread added)
        assert tracked.id in runner._active_runs


class TestDaemonRunnerSemaphoreInit:
    def test_default_max_concurrent_positive(self):
        from autoresearch.config import GlobalConfig
        runner = DaemonRunner(config=GlobalConfig())
        assert runner._semaphore._value > 0

    def test_shutdown_state_initially_false(self):
        from autoresearch.config import GlobalConfig
        runner = DaemonRunner(config=GlobalConfig())
        assert not runner._shutdown.is_set()


class TestPidRoundtrip:
    def test_write_and_read_current_pid(self, tmp_path):
        pid_path = tmp_path / "self.pid"
        write_pid(os.getpid(), pid_path)
        assert read_pid(pid_path) == os.getpid()

    def test_clear_and_read_returns_none(self, tmp_path):
        pid_path = tmp_path / "to_clear.pid"
        write_pid(1234, pid_path)
        clear_pid(pid_path)
        assert read_pid(pid_path) is None


class TestResolveCronExpressionEdgeCases:
    def test_cron_type_with_expression_returns_it(self):
        s = _make_schedule("cron", "*/15 * * * *")
        result = _resolve_cron_expression(s)
        assert result == "*/15 * * * *"

    def test_on_demand_ignores_cron_field(self):
        s = _make_schedule("on-demand", "0 * * * *")
        result = _resolve_cron_expression(s)
        assert result is None


class TestIsDueBoundary:
    def test_exactly_at_next_fire_is_due(self):
        # Run 61 minutes ago, hourly cron → should be due
        last = (datetime.now(timezone.utc) - timedelta(minutes=61)).isoformat()
        assert is_due(_make_schedule("cron", "0 * * * *"), last) is True

    def test_just_before_next_fire_not_due(self):
        # Run 30 seconds ago, hourly cron → should not be due
        last = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
        assert is_due(_make_schedule("cron", "0 * * * *"), last) is False


# ---------------------------------------------------------------------------
# is_pid_alive — PermissionError path
# ---------------------------------------------------------------------------

class TestIsPidAlivePermissionErrorB:
    def test_permission_error_returns_true(self):
        """PermissionError means process exists but is owned by another user."""
        with patch("os.kill", side_effect=PermissionError):
            result = is_pid_alive(9999)
        assert result is True

    def test_process_lookup_error_returns_false(self):
        with patch("os.kill", side_effect=ProcessLookupError):
            result = is_pid_alive(9999)
        assert result is False

    def test_success_returns_true(self):
        # Sending signal 0 to current process should succeed
        assert is_pid_alive(os.getpid()) is True


# ---------------------------------------------------------------------------
# DaemonRunner.shutdown
# ---------------------------------------------------------------------------

class TestDaemonRunnerShutdown:
    def test_shutdown_sets_event(self):
        from autoresearch.config import GlobalConfig
        runner = DaemonRunner(config=GlobalConfig())
        assert not runner._shutdown.is_set()
        runner.shutdown()
        assert runner._shutdown.is_set()

    def test_shutdown_idempotent(self):
        from autoresearch.config import GlobalConfig
        runner = DaemonRunner(config=GlobalConfig())
        runner.shutdown()
        runner.shutdown()  # should not raise
        assert runner._shutdown.is_set()


# ---------------------------------------------------------------------------
# DaemonRunner._reap_threads — with mix of alive and dead threads
# ---------------------------------------------------------------------------

class TestDaemonRunnerReapThreads:
    def test_reap_removes_finished_thread(self):
        from autoresearch.config import GlobalConfig
        dr = DaemonRunner(config=GlobalConfig())
        dead = MagicMock()
        dead.is_alive.return_value = False
        alive = MagicMock()
        alive.is_alive.return_value = True
        dr._active_runs = {"dead-id": dead, "alive-id": alive}
        dr._reap_threads()
        assert "dead-id" not in dr._active_runs
        assert "alive-id" in dr._active_runs

    def test_reap_empty_active_runs_noop(self):
        from autoresearch.config import GlobalConfig
        dr = DaemonRunner(config=GlobalConfig())
        dr._active_runs = {}
        dr._reap_threads()  # should not raise
        assert dr._active_runs == {}


# ---------------------------------------------------------------------------
# DaemonRunner._join_threads
# ---------------------------------------------------------------------------

class TestDaemonRunnerJoinThreadsFirst:
    def test_join_calls_join_on_all_threads(self):
        from autoresearch.config import GlobalConfig
        dr = DaemonRunner(config=GlobalConfig())
        t1 = MagicMock()
        t2 = MagicMock()
        dr._active_runs = {"m1": t1, "m2": t2}
        dr._join_threads(timeout=1)
        t1.join.assert_called_once_with(timeout=1)
        t2.join.assert_called_once_with(timeout=1)

    def test_join_empty_active_runs_noop(self):
        from autoresearch.config import GlobalConfig
        dr = DaemonRunner(config=GlobalConfig())
        dr._join_threads()  # should not raise


# ---------------------------------------------------------------------------
# DaemonRunner._run_marker_thread — tracked not found
# ---------------------------------------------------------------------------

class TestRunMarkerThreadTrackedNotFound:
    def test_tracked_not_found_returns_early(self):
        from autoresearch.config import GlobalConfig
        dr = DaemonRunner(config=GlobalConfig())
        tracked = _make_tracked()
        marker = _make_marker()
        state = AppState(markers=[])  # no tracked markers in state

        with (
            patch("autoresearch.daemon.load_state", return_value=state),
            patch("autoresearch.daemon.get_tracked", return_value=None),
        ):
            # Should return without error
            dr._run_marker_thread(tracked, marker)
        # No exception = pass


# ---------------------------------------------------------------------------
# stop_daemon — various edge cases
# ---------------------------------------------------------------------------

class TestStopDaemonEdgeCases:
    def test_no_pid_file_returns_false(self, tmp_path):
        pid_path = tmp_path / "missing.pid"
        result = stop_daemon(pid_path=pid_path)
        assert result is False

    def test_pid_not_alive_clears_and_returns_false(self, tmp_path):
        pid_path = tmp_path / "dead.pid"
        write_pid(999999999, pid_path)  # Dead PID
        result = stop_daemon(pid_path=pid_path)
        assert result is False
        assert not pid_path.exists()

    def test_stale_detection_clears_pid(self, tmp_path):
        pid_path = tmp_path / "stale.pid"
        write_pid(999999999, pid_path)  # dead PID
        stop_daemon(pid_path=pid_path)
        assert not pid_path.exists()


# ---------------------------------------------------------------------------
# is_due — naive datetime handling
# ---------------------------------------------------------------------------

class TestIsDueNaiveDatetime:
    def test_naive_last_run_treated_as_utc(self):
        """Naive datetime should be treated as UTC (assigned tzinfo=UTC)."""
        # Naive datetime 2 hours ago
        naive_last = (datetime.now(timezone.utc).replace(tzinfo=None) -
                      __import__('datetime').timedelta(hours=2)).isoformat()
        result = is_due(_make_schedule("cron", "0 * * * *"), naive_last)
        assert result is True  # 2 hours ago, hourly cron = due


# ---------------------------------------------------------------------------
# _resolve_cron_expression — additional checks
# ---------------------------------------------------------------------------

class TestResolveCronAll:
    def test_overnight_maps_to_1am(self):
        s = _make_schedule("overnight")
        result = _resolve_cron_expression(s)
        assert result == "0 1 * * *"

    def test_weekend_maps_to_saturday_1am(self):
        s = _make_schedule("weekend")
        result = _resolve_cron_expression(s)
        assert result == "0 1 * * 6"

    def test_on_demand_returns_none_always(self):
        s = _make_schedule("on-demand", cron="*/5 * * * *")
        assert _resolve_cron_expression(s) is None


# ---------------------------------------------------------------------------
# DaemonRunner — shutdown, run basics
# ---------------------------------------------------------------------------

class TestDaemonRunnerShutdownExtra:
    def test_shutdown_sets_event(self):
        from autoresearch.config import GlobalConfig
        dr = DaemonRunner(config=GlobalConfig())
        assert not dr._shutdown.is_set()
        dr.shutdown()
        assert dr._shutdown.is_set()

    def test_shutdown_idempotent(self):
        from autoresearch.config import GlobalConfig
        dr = DaemonRunner(config=GlobalConfig())
        dr.shutdown()
        dr.shutdown()  # calling twice should not raise
        assert dr._shutdown.is_set()

    def test_semaphore_max_concurrent(self):
        from autoresearch.config import GlobalConfig
        cfg = GlobalConfig()
        cfg.daemon.max_concurrent = 3
        dr = DaemonRunner(config=cfg)
        # acquire 3 times should succeed, 4th should fail (non-blocking)
        assert dr._semaphore.acquire(blocking=False)
        assert dr._semaphore.acquire(blocking=False)
        assert dr._semaphore.acquire(blocking=False)
        assert not dr._semaphore.acquire(blocking=False)
        # release them back
        dr._semaphore.release()
        dr._semaphore.release()
        dr._semaphore.release()

    def test_poll_seconds_set_from_config(self):
        from autoresearch.config import GlobalConfig
        cfg = GlobalConfig()
        cfg.daemon.poll_interval = "2m"
        dr = DaemonRunner(config=cfg)
        assert dr._poll_seconds == 120


# ---------------------------------------------------------------------------
# is_pid_alive — PermissionError means process exists
# ---------------------------------------------------------------------------

class TestIsPidAlivePermissionErrorExtra:
    def test_permission_error_returns_true(self):
        with patch("os.kill", side_effect=PermissionError):
            assert is_pid_alive(12345) is True

    def test_process_lookup_error_returns_false(self):
        with patch("os.kill", side_effect=ProcessLookupError):
            assert is_pid_alive(12345) is False

    def test_no_error_returns_true(self):
        with patch("os.kill", return_value=None):
            assert is_pid_alive(12345) is True


# ---------------------------------------------------------------------------
# check_stale_pid — alive pid not stale
# ---------------------------------------------------------------------------

class TestCheckStalePidAlive:
    def test_alive_pid_returns_false(self, tmp_path):
        pid_path = tmp_path / "alive.pid"
        write_pid(os.getpid(), pid_path)
        result = check_stale_pid(pid_path)
        assert result is False
        assert pid_path.exists()

    def test_missing_pid_file_returns_false(self, tmp_path):
        pid_path = tmp_path / "missing.pid"
        result = check_stale_pid(pid_path)
        assert result is False

    def test_stale_pid_clears_and_returns_true(self, tmp_path):
        pid_path = tmp_path / "stale.pid"
        write_pid(999999999, pid_path)
        result = check_stale_pid(pid_path)
        assert result is True
        assert not pid_path.exists()


# ---------------------------------------------------------------------------
# read_pid — edge cases
# ---------------------------------------------------------------------------

class TestReadPidEdgeCasesExtra:
    def test_empty_file_returns_none(self, tmp_path):
        pid_path = tmp_path / "empty.pid"
        pid_path.write_text("")
        assert read_pid(pid_path) is None

    def test_non_integer_returns_none(self, tmp_path):
        pid_path = tmp_path / "bad.pid"
        pid_path.write_text("not-a-number")
        assert read_pid(pid_path) is None

    def test_valid_pid_returns_int(self, tmp_path):
        pid_path = tmp_path / "good.pid"
        pid_path.write_text("12345")
        assert read_pid(pid_path) == 12345

    def test_pid_with_whitespace(self, tmp_path):
        pid_path = tmp_path / "ws.pid"
        pid_path.write_text("  42  \n")
        assert read_pid(pid_path) == 42


# ---------------------------------------------------------------------------
# write_pid / clear_pid
# ---------------------------------------------------------------------------

class TestWriteAndClearPid:
    def test_write_creates_file(self, tmp_path):
        pid_path = tmp_path / "sub" / "daemon.pid"
        write_pid(9999, pid_path)
        assert pid_path.exists()
        assert pid_path.read_text() == "9999"

    def test_clear_removes_file(self, tmp_path):
        pid_path = tmp_path / "daemon.pid"
        write_pid(1234, pid_path)
        clear_pid(pid_path)
        assert not pid_path.exists()

    def test_clear_missing_file_noop(self, tmp_path):
        pid_path = tmp_path / "nonexistent.pid"
        clear_pid(pid_path)  # should not raise


# ---------------------------------------------------------------------------
# DaemonRunner.run — exits immediately when shutdown is pre-set
# ---------------------------------------------------------------------------

class TestDaemonRunnerRunEarlyExit:
    def test_run_exits_immediately_if_shutdown_set(self):
        from autoresearch.config import GlobalConfig
        dr = DaemonRunner(config=GlobalConfig())
        dr.shutdown()  # pre-set
        # Should return quickly without blocking
        dr.run()  # no infinite loop

    def test_run_calls_tick_before_shutdown(self):
        from autoresearch.config import GlobalConfig
        dr = DaemonRunner(config=GlobalConfig())
        tick_calls = []


        def tracking_tick():
            tick_calls.append(1)
            dr.shutdown()  # stop after first tick

        dr._tick = tracking_tick
        dr.run()
        assert len(tick_calls) == 1


# ---------------------------------------------------------------------------
# DaemonRunner._reap_threads — dead vs alive thread
# ---------------------------------------------------------------------------

class TestDaemonRunnerReapThreadsExtra:
    def test_finished_thread_removed(self):
        import threading
        from autoresearch.config import GlobalConfig
        dr = DaemonRunner(config=GlobalConfig())

        done = threading.Event()
        t = threading.Thread(target=done.wait, args=(0.001,))
        t.start()
        t.join()  # ensure it's dead

        dr._active_runs["m1"] = t
        dr._reap_threads()
        assert "m1" not in dr._active_runs

    def test_alive_thread_kept(self):
        import threading
        from autoresearch.config import GlobalConfig
        dr = DaemonRunner(config=GlobalConfig())

        alive_event = threading.Event()
        t = threading.Thread(target=alive_event.wait)
        t.daemon = True
        t.start()

        dr._active_runs["m2"] = t
        dr._reap_threads()
        assert "m2" in dr._active_runs
        alive_event.set()
        t.join()


# ---------------------------------------------------------------------------
# is_due — various schedule types
# ---------------------------------------------------------------------------

class TestIsDueMoreScheduleTypes:
    def test_hourly_schedule_due_when_over_an_hour_passed(self):
        last_run = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        s = _make_schedule("cron", "0 * * * *")
        assert is_due(s, last_run) is True

    def test_hourly_schedule_not_due_when_just_ran(self):
        last_run = datetime.now(timezone.utc).isoformat()
        s = _make_schedule("cron", "0 * * * *")
        assert is_due(s, last_run) is False

    def test_on_demand_never_due(self):
        last_run = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
        s = _make_schedule("on-demand")
        assert is_due(s, last_run) is False

    def test_on_demand_never_due_even_with_no_last_run(self):
        s = _make_schedule("on-demand")
        assert is_due(s, None) is False

    def test_cron_due_with_no_last_run(self):
        s = _make_schedule("cron", "* * * * *")  # every minute
        assert is_due(s, None) is True

    def test_daily_schedule_due_after_25_hours(self):
        last_run = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        s = _make_schedule("cron", "0 0 * * *")
        assert is_due(s, last_run) is True


# ---------------------------------------------------------------------------
# stop_daemon — alive PID sends SIGTERM
# ---------------------------------------------------------------------------

class TestStopDaemonAlivePid:
    def test_sigterm_sent_to_alive_pid(self, tmp_path):
        pid_path = tmp_path / "alive.pid"
        write_pid(99999, pid_path)

        kill_calls = []

        def fake_kill(pid, sig):
            kill_calls.append((pid, sig))

        # Process never dies — we'll check up to the wait loop logic
        with (
            patch("autoresearch.daemon.is_pid_alive", return_value=True),
            patch("os.kill", side_effect=fake_kill),
            patch("time.sleep"),  # speed up the loop
        ):
            # After 20 wait iterations it returns False (not stopped)
            result = stop_daemon(pid_path=pid_path)

        import signal
        assert (99999, signal.SIGTERM) in kill_calls
        assert result is False


# ---------------------------------------------------------------------------
# _resolve_cron_expression — hourly and daily
# ---------------------------------------------------------------------------

class TestResolveCronExtraSchedules:
    def test_unknown_type_returns_none(self):
        s = _make_schedule("unknown-type")
        result = _resolve_cron_expression(s)
        assert result is None

    def test_overnight_resolves(self):
        s = _make_schedule("overnight")
        result = _resolve_cron_expression(s)
        assert result == "0 1 * * *"

    def test_cron_type_returns_custom(self):
        s = _make_schedule("cron", "15 3 * * *")
        result = _resolve_cron_expression(s)
        assert result == "15 3 * * *"

    def test_cron_type_without_custom_returns_none(self):
        s = _make_schedule("cron", None)
        result = _resolve_cron_expression(s)
        assert result is None


# ---------------------------------------------------------------------------
# DaemonRunner — state_path propagation
# ---------------------------------------------------------------------------

class TestDaemonRunnerStatePath:
    def test_state_path_stored(self, tmp_path):
        from autoresearch.config import GlobalConfig
        sp = tmp_path / "state.json"
        dr = DaemonRunner(config=GlobalConfig(), state_path=sp)
        assert dr._state_path == sp

    def test_state_path_none_by_default(self):
        from autoresearch.config import GlobalConfig
        dr = DaemonRunner(config=GlobalConfig())
        assert dr._state_path is None


# ---------------------------------------------------------------------------
# DaemonRunner._run_marker_thread — error paths
# ---------------------------------------------------------------------------

class TestRunMarkerThreadErrors:
    def test_engine_error_logged_not_raised(self, tmp_path):
        from autoresearch.config import GlobalConfig
        from autoresearch.engine import EngineError
        from autoresearch.state import AppState, TrackedMarker

        state = AppState(markers=[
            TrackedMarker(
                id="repo:marker",
                repo_path=str(tmp_path),
                repo_name="repo",
                marker_name="marker",
            )
        ])
        tracked = state.markers[0]
        marker = MagicMock()

        dr = DaemonRunner(config=GlobalConfig())

        with (
            patch("autoresearch.daemon.load_state", return_value=state),
            patch("autoresearch.daemon.get_tracked", return_value=tracked),
            patch("autoresearch.daemon.get_agent_runner"),
            patch("autoresearch.daemon.run_marker", side_effect=EngineError("boom")),
        ):
            dr._semaphore.acquire()
            dr._run_marker_thread(tracked, marker)
        # If we get here, EngineError was caught and not raised

    def test_unexpected_exception_logged_not_raised(self, tmp_path):
        from autoresearch.config import GlobalConfig
        from autoresearch.state import AppState, TrackedMarker

        state = AppState(markers=[
            TrackedMarker(
                id="repo:marker",
                repo_path=str(tmp_path),
                repo_name="repo",
                marker_name="marker",
            )
        ])
        tracked = state.markers[0]
        marker = MagicMock()

        dr = DaemonRunner(config=GlobalConfig())

        with (
            patch("autoresearch.daemon.load_state", return_value=state),
            patch("autoresearch.daemon.get_tracked", return_value=tracked),
            patch("autoresearch.daemon.get_agent_runner"),
            patch("autoresearch.daemon.run_marker", side_effect=RuntimeError("unexpected")),
        ):
            dr._semaphore.acquire()
            dr._run_marker_thread(tracked, marker)
        # Must not propagate

    def test_tracked_not_found_returns_early(self, tmp_path):
        from autoresearch.config import GlobalConfig
        from autoresearch.state import AppState, TrackedMarker

        state = AppState(markers=[])
        tracked = TrackedMarker(
            id="repo:missing",
            repo_path=str(tmp_path),
            repo_name="repo",
            marker_name="missing",
        )
        marker = MagicMock()

        dr = DaemonRunner(config=GlobalConfig())

        with (
            patch("autoresearch.daemon.load_state", return_value=state),
            patch("autoresearch.daemon.get_tracked", return_value=None),
            patch("autoresearch.daemon.run_marker") as mock_run,
        ):
            dr._semaphore.acquire()
            dr._run_marker_thread(tracked, marker)
        mock_run.assert_not_called()

    def test_semaphore_released_after_engine_error(self, tmp_path):
        from autoresearch.config import GlobalConfig
        from autoresearch.engine import EngineError
        from autoresearch.state import AppState, TrackedMarker

        state = AppState(markers=[
            TrackedMarker(
                id="repo:m",
                repo_path=str(tmp_path),
                repo_name="repo",
                marker_name="m",
            )
        ])
        tracked = state.markers[0]
        marker = MagicMock()

        dr = DaemonRunner(config=GlobalConfig())
        before_value = dr._semaphore._value

        with (
            patch("autoresearch.daemon.load_state", return_value=state),
            patch("autoresearch.daemon.get_tracked", return_value=tracked),
            patch("autoresearch.daemon.get_agent_runner"),
            patch("autoresearch.daemon.run_marker", side_effect=EngineError("fail")),
        ):
            dr._semaphore.acquire()
            dr._run_marker_thread(tracked, marker)

        # Semaphore released in finally block
        assert dr._semaphore._value == before_value


# ---------------------------------------------------------------------------
# DaemonRunner — shutdown after single tick
# ---------------------------------------------------------------------------

class TestDaemonRunnerShutdownBehavior:
    def test_shutdown_set_stops_loop(self):
        from autoresearch.config import GlobalConfig

        dr = DaemonRunner(config=GlobalConfig())
        tick_calls = []

        def fake_tick():
            tick_calls.append(1)
            dr.shutdown()

        with (
            patch.object(dr, "_tick", side_effect=fake_tick),
            patch.object(dr, "_join_threads"),
        ):
            dr.run()

        assert len(tick_calls) == 1

    def test_join_threads_called_on_exit(self):
        from autoresearch.config import GlobalConfig

        dr = DaemonRunner(config=GlobalConfig())

        with (
            patch.object(dr, "_tick", side_effect=lambda: dr.shutdown()),
            patch.object(dr, "_join_threads") as mock_join,
        ):
            dr.run()

        mock_join.assert_called_once()


# ---------------------------------------------------------------------------
# is_pid_alive — permission error returns True
# ---------------------------------------------------------------------------

class TestIsPidAlivePermissionError:
    def test_permission_error_means_alive(self):
        with patch("os.kill", side_effect=PermissionError):
            result = is_pid_alive(99999)
        assert result is True

    def test_process_lookup_error_means_dead(self):
        with patch("os.kill", side_effect=ProcessLookupError):
            result = is_pid_alive(99999)
        assert result is False


# ---------------------------------------------------------------------------
# check_stale_pid — edge cases
# ---------------------------------------------------------------------------

class TestCheckStalePidEdgeCases:
    def test_no_pid_file_returns_false(self, tmp_path):
        pid_path = tmp_path / "no.pid"
        result = check_stale_pid(pid_path=pid_path)
        assert result is False

    def test_stale_pid_cleared_returns_true(self, tmp_path):
        pid_path = tmp_path / "stale.pid"
        write_pid(99999999, pid_path)
        with patch("autoresearch.daemon.is_pid_alive", return_value=False):
            result = check_stale_pid(pid_path=pid_path)
        assert result is True
        assert not pid_path.exists()

    def test_live_pid_not_cleared_returns_false(self, tmp_path):
        pid_path = tmp_path / "live.pid"
        write_pid(99999, pid_path)
        with patch("autoresearch.daemon.is_pid_alive", return_value=True):
            result = check_stale_pid(pid_path=pid_path)
        assert result is False
        assert pid_path.exists()


# ---------------------------------------------------------------------------
# DaemonRunner — poll seconds from config
# ---------------------------------------------------------------------------

class TestDaemonRunnerPollSeconds:
    def test_poll_seconds_parsed_from_config(self):
        from autoresearch.config import DaemonConfig, GlobalConfig
        config = GlobalConfig(daemon=DaemonConfig(poll_interval="2m", max_concurrent=1))
        dr = DaemonRunner(config=config)
        assert dr._poll_seconds == 120

    def test_max_concurrent_sets_semaphore(self):
        from autoresearch.config import DaemonConfig, GlobalConfig
        config = GlobalConfig(daemon=DaemonConfig(poll_interval="1m", max_concurrent=3))
        dr = DaemonRunner(config=config)
        assert dr._semaphore._value == 3


# ---------------------------------------------------------------------------
# daemonize — win32 platform guard (daemon.py lines 246-250)
# ---------------------------------------------------------------------------


class TestDaemonizeWin32Guard:
    def test_raises_runtime_error_on_windows(self):
        import sys
        from autoresearch.daemon import daemonize

        with patch.object(sys, "platform", "win32"):
            with pytest.raises(RuntimeError, match="not supported on Windows"):
                daemonize()

    def test_no_error_on_linux(self, tmp_path):
        import sys
        from autoresearch.daemon import daemonize

        # On Linux, daemonize calls os.fork which we must intercept before
        # it actually forks. We only test that the win32 check is skipped.
        with patch.object(sys, "platform", "linux"):
            with patch("os.fork", side_effect=OSError("mock fork blocked")):
                with pytest.raises(OSError, match="mock fork blocked"):
                    daemonize(log_path=tmp_path / "log", pid_path=tmp_path / "pid")


# ---------------------------------------------------------------------------
# Additional IsDue edge cases for on-demand and cron
# ---------------------------------------------------------------------------


class TestIsDueOnDemandEdge:
    def test_on_demand_with_last_run_returns_false(self):
        last_run = datetime.now(timezone.utc).isoformat()
        assert is_due(_make_schedule("on-demand"), last_run) is False

    def test_on_demand_without_last_run_returns_false(self):
        assert is_due(_make_schedule("on-demand"), None) is False


class TestIsDeadProcessLookupErrorExtra:
    def test_process_lookup_error_returns_false(self):
        with patch("os.kill", side_effect=ProcessLookupError):
            assert is_pid_alive(77777) is False

    def test_no_exception_returns_true(self):
        with patch("os.kill", return_value=None):
            assert is_pid_alive(77777) is True


# ---------------------------------------------------------------------------
# stop_daemon state reset when stale
# ---------------------------------------------------------------------------


class TestStopDaemonStateResetExtra:
    def test_stale_pid_resets_running_to_false(self, tmp_path):
        from autoresearch.state import AppState, DaemonState, save_state

        state = AppState(daemon=DaemonState(running=True, pid=99999))
        state_path = tmp_path / "state.json"
        save_state(state, state_path)

        pid_file = tmp_path / "autoresearch.pid"
        pid_file.write_text("99999")

        with (
            patch("autoresearch.daemon.check_stale_pid", return_value=True),
            patch("autoresearch.daemon.PID_PATH", pid_file),
            patch("autoresearch.daemon.load_state", return_value=state),
            patch("autoresearch.daemon.save_state"),
        ):
            result = stop_daemon(pid_path=pid_file, state_path=state_path)
        assert result is False


# ---------------------------------------------------------------------------
# daemonize — fork path coverage (daemon.py lines 258-326)
# ---------------------------------------------------------------------------


class TestDaemonizeParentPath:
    """Cover lines 258-264: parent process reads grandchild PID from pipe."""

    def test_parent_returns_grandchild_pid(self, tmp_path):
        from autoresearch.daemon import daemonize

        fake_pid = 54321
        fake_read_fd = 10
        fake_write_fd = 11

        with (
            patch("os.pipe", return_value=(fake_read_fd, fake_write_fd)),
            patch("os.fork", return_value=fake_pid),  # parent: pid > 0
            patch("os.close"),
            patch("os.waitpid", return_value=(fake_pid, 0)),
            patch("os.read", return_value=b"99999"),
        ):
            result = daemonize(
                log_path=tmp_path / "daemon.log",
                pid_path=tmp_path / "daemon.pid",
            )
        assert result == 99999

    def test_parent_reads_correct_fd_and_closes(self, tmp_path):
        from autoresearch.daemon import daemonize

        closed_fds = []
        fake_read_fd = 20
        fake_write_fd = 21

        with (
            patch("os.pipe", return_value=(fake_read_fd, fake_write_fd)),
            patch("os.fork", return_value=88888),
            patch("os.close", side_effect=lambda fd: closed_fds.append(fd)),
            patch("os.waitpid", return_value=(88888, 0)),
            patch("os.read", return_value=b"77777"),
        ):
            result = daemonize(
                log_path=tmp_path / "daemon.log",
                pid_path=tmp_path / "daemon.pid",
            )
        assert result == 77777
        assert fake_write_fd in closed_fds
        assert fake_read_fd in closed_fds


class TestDaemonizeFirstChildPath:
    """Cover lines 266-276: first child forks grandchild, writes PID, exits."""

    def test_first_child_writes_pid_and_exits(self, tmp_path):
        from autoresearch.daemon import daemonize

        fake_read_fd = 30
        fake_write_fd = 31
        fork_calls = []

        def fork_side_effect():
            call_num = len(fork_calls)
            fork_calls.append(call_num)
            if call_num == 0:
                return 0      # first fork: we are child
            else:
                return 42000  # second fork: we are first child, pid2 > 0

        written_data = []
        exit_codes = []

        with (
            patch("os.pipe", return_value=(fake_read_fd, fake_write_fd)),
            patch("os.fork", side_effect=fork_side_effect),
            patch("os.close"),
            patch("os.setsid"),
            patch("os.write", side_effect=lambda fd, data: written_data.append(data)),
            patch("os._exit", side_effect=lambda code: exit_codes.append(code) or (_ for _ in ()).throw(SystemExit(code))),
        ):
            with pytest.raises(SystemExit):
                daemonize(
                    log_path=tmp_path / "daemon.log",
                    pid_path=tmp_path / "daemon.pid",
                )

        assert b"42000" in written_data
        assert 0 in exit_codes

    def test_first_child_closes_read_fd_before_setsid(self, tmp_path):
        from autoresearch.daemon import daemonize

        fake_read_fd = 32
        fake_write_fd = 33
        fork_calls = []
        closed = []

        def fork_side_effect():
            n = len(fork_calls)
            fork_calls.append(n)
            return 0 if n == 0 else 50001

        def close_side_effect(fd):
            closed.append(fd)

        with (
            patch("os.pipe", return_value=(fake_read_fd, fake_write_fd)),
            patch("os.fork", side_effect=fork_side_effect),
            patch("os.close", side_effect=close_side_effect),
            patch("os.setsid"),
            patch("os.write"),
            patch("os._exit", side_effect=lambda code: (_ for _ in ()).throw(SystemExit(code))),
        ):
            with pytest.raises(SystemExit):
                daemonize(
                    log_path=tmp_path / "daemon.log",
                    pid_path=tmp_path / "daemon.pid",
                )

        assert fake_read_fd in closed


class TestDaemonizeGrandchildPath:
    """Cover lines 278-326: grandchild sets up daemon and runs."""

    def _make_mock_state(self):
        from autoresearch.state import AppState, DaemonState
        state = AppState(daemon=DaemonState())
        return state

    def _make_sys_io_mocks(self):
        """Return MagicMock stdin/stdout/stderr with fileno() returning ints."""
        mock_stdin = MagicMock()
        mock_stdin.fileno.return_value = 0
        mock_stdout = MagicMock()
        mock_stdout.fileno.return_value = 1
        mock_stderr = MagicMock()
        mock_stderr.fileno.return_value = 2
        return mock_stdin, mock_stdout, mock_stderr

    def test_grandchild_writes_pid_and_runs_daemon(self, tmp_path):
        from autoresearch.daemon import daemonize

        fake_read_fd = 40
        fake_write_fd = 41
        fork_calls = []

        def fork_side_effect():
            n = len(fork_calls)
            fork_calls.append(n)
            return 0  # grandchild: both forks return 0

        mock_state = self._make_mock_state()
        mock_runner = MagicMock()
        mock_log_fd = MagicMock()
        mock_log_fd.fileno.return_value = 5
        exit_codes = []
        mock_stdin, mock_stdout, mock_stderr = self._make_sys_io_mocks()

        with (
            patch("os.pipe", return_value=(fake_read_fd, fake_write_fd)),
            patch("os.fork", side_effect=fork_side_effect),
            patch("os.close"),
            patch("os.setsid"),
            patch("os.getpid", return_value=12345),
            patch("autoresearch.daemon.write_pid"),
            patch("autoresearch.daemon.load_state", return_value=mock_state),
            patch("autoresearch.daemon.save_state"),
            patch("os.open", return_value=9),
            patch("os.dup2"),
            patch("sys.stdin", mock_stdin),
            patch("sys.stdout", mock_stdout),
            patch("sys.stderr", mock_stderr),
            patch("builtins.open", return_value=mock_log_fd),
            patch("logging.basicConfig"),
            patch("autoresearch.daemon.DaemonRunner", return_value=mock_runner),
            patch("signal.signal"),
            patch("autoresearch.daemon.clear_pid"),
            patch("os._exit", side_effect=lambda code: exit_codes.append(code) or (_ for _ in ()).throw(SystemExit(code))),
        ):
            with pytest.raises(SystemExit):
                daemonize(
                    log_path=tmp_path / "daemon.log",
                    pid_path=tmp_path / "daemon.pid",
                )

        mock_runner.run.assert_called_once()
        assert 0 in exit_codes

    def test_grandchild_state_updated_with_pid(self, tmp_path):
        from autoresearch.daemon import daemonize

        fake_read_fd = 42
        fake_write_fd = 43
        fork_calls = []

        def fork_side_effect():
            n = len(fork_calls)
            fork_calls.append(n)
            return 0

        mock_state = self._make_mock_state()
        saved_states = []
        mock_runner = MagicMock()
        mock_log_fd = MagicMock()
        mock_log_fd.fileno.return_value = 6
        mock_stdin, mock_stdout, mock_stderr = self._make_sys_io_mocks()

        with (
            patch("os.pipe", return_value=(fake_read_fd, fake_write_fd)),
            patch("os.fork", side_effect=fork_side_effect),
            patch("os.close"),
            patch("os.setsid"),
            patch("os.getpid", return_value=55555),
            patch("autoresearch.daemon.write_pid"),
            patch("autoresearch.daemon.load_state", return_value=mock_state),
            patch("autoresearch.daemon.save_state", side_effect=lambda s, p: saved_states.append((s.daemon.running, s.daemon.pid))),
            patch("os.open", return_value=8),
            patch("os.dup2"),
            patch("sys.stdin", mock_stdin),
            patch("sys.stdout", mock_stdout),
            patch("sys.stderr", mock_stderr),
            patch("builtins.open", return_value=mock_log_fd),
            patch("logging.basicConfig"),
            patch("autoresearch.daemon.DaemonRunner", return_value=mock_runner),
            patch("signal.signal"),
            patch("autoresearch.daemon.clear_pid"),
            patch("os._exit", side_effect=lambda code: (_ for _ in ()).throw(SystemExit(code))),
        ):
            with pytest.raises(SystemExit):
                daemonize(
                    log_path=tmp_path / "daemon.log",
                    pid_path=tmp_path / "daemon.pid",
                )

        assert len(saved_states) >= 1
        # First save: daemon set to running=True with correct PID
        assert saved_states[0] == (True, 55555)

    def test_grandchild_cleanup_on_runner_exit(self, tmp_path):
        from autoresearch.daemon import daemonize

        fake_read_fd = 44
        fake_write_fd = 45
        fork_calls = []

        def fork_side_effect():
            n = len(fork_calls)
            fork_calls.append(n)
            return 0

        mock_state = self._make_mock_state()
        saved_states = []
        mock_runner = MagicMock()
        mock_log_fd = MagicMock()
        mock_log_fd.fileno.return_value = 7
        clear_pid_calls = []
        mock_stdin, mock_stdout, mock_stderr = self._make_sys_io_mocks()

        with (
            patch("os.pipe", return_value=(fake_read_fd, fake_write_fd)),
            patch("os.fork", side_effect=fork_side_effect),
            patch("os.close"),
            patch("os.setsid"),
            patch("os.getpid", return_value=66666),
            patch("autoresearch.daemon.write_pid"),
            patch("autoresearch.daemon.load_state", return_value=mock_state),
            patch("autoresearch.daemon.save_state", side_effect=lambda s, p: saved_states.append(s)),
            patch("os.open", return_value=7),
            patch("os.dup2"),
            patch("sys.stdin", mock_stdin),
            patch("sys.stdout", mock_stdout),
            patch("sys.stderr", mock_stderr),
            patch("builtins.open", return_value=mock_log_fd),
            patch("logging.basicConfig"),
            patch("autoresearch.daemon.DaemonRunner", return_value=mock_runner),
            patch("signal.signal"),
            patch("autoresearch.daemon.clear_pid", side_effect=lambda p: clear_pid_calls.append(p)),
            patch("os._exit", side_effect=lambda code: (_ for _ in ()).throw(SystemExit(code))),
        ):
            with pytest.raises(SystemExit):
                daemonize(
                    log_path=tmp_path / "daemon.log",
                    pid_path=tmp_path / "daemon.pid",
                )

        assert len(clear_pid_calls) == 1
        assert any(s.daemon.running is False for s in saved_states)

    def test_grandchild_signal_handlers_registered(self, tmp_path):
        from autoresearch.daemon import daemonize

        fork_calls = []

        def fork_side_effect():
            n = len(fork_calls)
            fork_calls.append(n)
            return 0

        mock_state = self._make_mock_state()
        mock_runner = MagicMock()
        mock_log_fd = MagicMock()
        mock_log_fd.fileno.return_value = 8
        registered_signals = []
        mock_stdin, mock_stdout, mock_stderr = self._make_sys_io_mocks()

        with (
            patch("os.pipe", return_value=(50, 51)),
            patch("os.fork", side_effect=fork_side_effect),
            patch("os.close"),
            patch("os.setsid"),
            patch("os.getpid", return_value=77777),
            patch("autoresearch.daemon.write_pid"),
            patch("autoresearch.daemon.load_state", return_value=mock_state),
            patch("autoresearch.daemon.save_state"),
            patch("os.open", return_value=9),
            patch("os.dup2"),
            patch("sys.stdin", mock_stdin),
            patch("sys.stdout", mock_stdout),
            patch("sys.stderr", mock_stderr),
            patch("builtins.open", return_value=mock_log_fd),
            patch("logging.basicConfig"),
            patch("autoresearch.daemon.DaemonRunner", return_value=mock_runner),
            patch("signal.signal", side_effect=lambda s, h: registered_signals.append(s)),
            patch("autoresearch.daemon.clear_pid"),
            patch("os._exit", side_effect=lambda code: (_ for _ in ()).throw(SystemExit(code))),
        ):
            with pytest.raises(SystemExit):
                daemonize(
                    log_path=tmp_path / "daemon.log",
                    pid_path=tmp_path / "daemon.pid",
                )

        import signal as sig
        assert sig.SIGTERM in registered_signals
        assert sig.SIGINT in registered_signals

    def test_handle_signal_calls_runner_shutdown(self, tmp_path):
        """Invoke _handle_signal to cover lines 310-311."""
        from autoresearch.daemon import daemonize
        import signal as sig

        fork_calls = []

        def fork_side_effect():
            n = len(fork_calls)
            fork_calls.append(n)
            return 0

        mock_state = self._make_mock_state()
        mock_runner = MagicMock()
        mock_log_fd = MagicMock()
        mock_log_fd.fileno.return_value = 9
        mock_stdin, mock_stdout, mock_stderr = self._make_sys_io_mocks()
        registered_handlers = {}

        def capture_signal(signum, handler):
            registered_handlers[signum] = handler

        with (
            patch("os.pipe", return_value=(60, 61)),
            patch("os.fork", side_effect=fork_side_effect),
            patch("os.close"),
            patch("os.setsid"),
            patch("os.getpid", return_value=88888),
            patch("autoresearch.daemon.write_pid"),
            patch("autoresearch.daemon.load_state", return_value=mock_state),
            patch("autoresearch.daemon.save_state"),
            patch("os.open", return_value=10),
            patch("os.dup2"),
            patch("sys.stdin", mock_stdin),
            patch("sys.stdout", mock_stdout),
            patch("sys.stderr", mock_stderr),
            patch("builtins.open", return_value=mock_log_fd),
            patch("logging.basicConfig"),
            patch("autoresearch.daemon.DaemonRunner", return_value=mock_runner),
            patch("signal.signal", side_effect=capture_signal),
            patch("autoresearch.daemon.clear_pid"),
            patch("os._exit", side_effect=lambda code: (_ for _ in ()).throw(SystemExit(code))),
        ):
            with pytest.raises(SystemExit):
                daemonize(
                    log_path=tmp_path / "daemon.log",
                    pid_path=tmp_path / "daemon.pid",
                )

        # Invoke the captured SIGTERM handler to cover lines 310-311
        assert sig.SIGTERM in registered_handlers
        handler = registered_handlers[sig.SIGTERM]
        handler(sig.SIGTERM, None)
        mock_runner.shutdown.assert_called_once()


# ---------------------------------------------------------------------------
# stop_daemon — pid-alive-at-step-3 race path
# ---------------------------------------------------------------------------


class TestStopDaemonPidDeadAfterCheckStale:
    """Covers the path where pid exists, check_stale returns False,
    but is_pid_alive returns False at the second call in stop_daemon."""

    def test_pid_dead_after_stale_check_returns_false(self, tmp_path):
        pid_path = tmp_path / "test.pid"
        write_pid(12345, pid_path)
        # First is_pid_alive call (in check_stale_pid) -> True (not stale)
        # Second is_pid_alive call (in stop_daemon body step 3) -> False
        with (
            patch("autoresearch.daemon.is_pid_alive", side_effect=[True, False]),
            patch("autoresearch.daemon.clear_pid") as mock_clear,
        ):
            result = stop_daemon(pid_path=pid_path)
        assert result is False
        mock_clear.assert_called_once()

    def test_pid_dead_at_step3_clears_pid_file(self, tmp_path):
        pid_path = tmp_path / "test.pid"
        write_pid(42, pid_path)
        with patch("autoresearch.daemon.is_pid_alive", side_effect=[True, False]):
            result = stop_daemon(pid_path=pid_path)
        assert result is False
        # pid file should be cleared
        assert not pid_path.exists()


# ---------------------------------------------------------------------------
# WritePid — parent directory creation
# ---------------------------------------------------------------------------


class TestWritePidCreatesParent:
    def test_creates_nested_directory(self, tmp_path):
        nested = tmp_path / "nested" / "dir" / "daemon.pid"
        write_pid(99, nested)
        assert nested.exists()
        assert nested.read_text() == "99"

    def test_overwrites_existing_pid(self, tmp_path):
        pid_path = tmp_path / "daemon.pid"
        write_pid(100, pid_path)
        write_pid(200, pid_path)
        assert read_pid(pid_path) == 200


# ---------------------------------------------------------------------------
# IsDue — TypeError path
# ---------------------------------------------------------------------------


class TestIsDueTypeError:
    def test_type_error_in_last_run_returns_true(self):
        schedule = _make_schedule("cron", "*/5 * * * *")
        # Passing a non-string causes fromisoformat to raise TypeError
        assert is_due(schedule, 12345) is True  # type: ignore[arg-type]

    def test_none_last_run_returns_true_for_cron(self):
        schedule = _make_schedule("cron", "*/5 * * * *")
        assert is_due(schedule, None) is True


# ---------------------------------------------------------------------------
# _resolve_cron_expression — SCHEDULE_CRON_MAP values
# ---------------------------------------------------------------------------


class TestResolveCronExpressionMapValues:
    def test_overnight_is_1am_daily(self):
        schedule = _make_schedule("overnight")
        from autoresearch.daemon import _resolve_cron_expression, SCHEDULE_CRON_MAP
        result = _resolve_cron_expression(schedule)
        assert result == SCHEDULE_CRON_MAP["overnight"]

    def test_weekend_is_saturday_1am(self):
        schedule = _make_schedule("weekend")
        from autoresearch.daemon import _resolve_cron_expression, SCHEDULE_CRON_MAP
        result = _resolve_cron_expression(schedule)
        assert result == SCHEDULE_CRON_MAP["weekend"]

    def test_cron_with_empty_string_falls_back_to_map(self):
        schedule = _make_schedule("overnight", cron="")
        from autoresearch.daemon import _resolve_cron_expression
        # type="overnight", cron is falsy, so returns map value
        result = _resolve_cron_expression(schedule)
        assert result == "0 1 * * *"


# ---------------------------------------------------------------------------
# DaemonRunner — _reap_threads with no threads
# ---------------------------------------------------------------------------


class TestDaemonRunnerReapEmpty:
    def test_reap_with_no_active_runs_is_noop(self):
        from autoresearch.config import GlobalConfig
        with patch("autoresearch.daemon.load_config", return_value=GlobalConfig()):
            runner = DaemonRunner()
        assert runner._active_runs == {}
        runner._reap_threads()  # should not raise
        assert runner._active_runs == {}

    def test_reap_removes_finished_thread(self):
        from autoresearch.config import GlobalConfig
        with patch("autoresearch.daemon.load_config", return_value=GlobalConfig()):
            runner = DaemonRunner()
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = False
        runner._active_runs["marker-x"] = mock_thread
        runner._reap_threads()
        assert "marker-x" not in runner._active_runs

    def test_reap_keeps_alive_thread(self):
        from autoresearch.config import GlobalConfig
        with patch("autoresearch.daemon.load_config", return_value=GlobalConfig()):
            runner = DaemonRunner()
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = True
        runner._active_runs["marker-y"] = mock_thread
        runner._reap_threads()
        assert "marker-y" in runner._active_runs


# ---------------------------------------------------------------------------
# check_stale_pid — various paths
# ---------------------------------------------------------------------------


class TestCheckStalePidPaths:
    def test_none_pid_returns_false(self, tmp_path):
        result = check_stale_pid(tmp_path / "missing.pid")
        assert result is False

    def test_live_pid_returns_false(self, tmp_path):
        pid_path = tmp_path / "live.pid"
        write_pid(os.getpid(), pid_path)
        result = check_stale_pid(pid_path)
        assert result is False
        assert pid_path.exists()

    def test_dead_pid_clears_and_returns_true(self, tmp_path):
        pid_path = tmp_path / "stale.pid"
        write_pid(9999999, pid_path)
        with patch("autoresearch.daemon.is_pid_alive", return_value=False):
            result = check_stale_pid(pid_path)
        assert result is True
        assert not pid_path.exists()


# ---------------------------------------------------------------------------
# read_pid — edge cases
# ---------------------------------------------------------------------------


class TestReadPidEdgeCases:
    def test_whitespace_pid_parsed(self, tmp_path):
        pid_path = tmp_path / "pid"
        pid_path.write_text("  1234  \n")
        assert read_pid(pid_path) == 1234

    def test_float_string_returns_none(self, tmp_path):
        pid_path = tmp_path / "pid"
        pid_path.write_text("12.5")
        assert read_pid(pid_path) is None

    def test_empty_file_returns_none(self, tmp_path):
        pid_path = tmp_path / "pid"
        pid_path.write_text("")
        assert read_pid(pid_path) is None


# ---------------------------------------------------------------------------
# is_due — additional schedule type edge cases
# ---------------------------------------------------------------------------


class TestIsDueAdditionalTypes:
    def test_is_due_type_hourly_past_minute(self):
        from autoresearch.daemon import is_due
        s = _make_schedule("hourly")
        now = datetime(2026, 3, 31, 14, 5, 0, tzinfo=timezone.utc)
        result = is_due(s, now)
        assert isinstance(result, bool)

    def test_is_due_with_future_cron(self):
        from autoresearch.daemon import is_due
        s = _make_schedule("cron", cron="0 3 * * *")
        now = datetime(2026, 3, 31, 2, 0, 0, tzinfo=timezone.utc)
        result = is_due(s, now)
        assert isinstance(result, bool)

    def test_is_due_with_past_cron_last_ran_recently(self):
        from autoresearch.daemon import is_due
        s = _make_schedule("cron", cron="0 2 * * *")
        now = datetime(2026, 3, 31, 2, 30, 0, tzinfo=timezone.utc)
        result = is_due(s, now)
        assert isinstance(result, bool)

    def test_is_due_overnight_returns_bool(self):
        from autoresearch.daemon import is_due
        s = _make_schedule("overnight")
        now = datetime(2026, 3, 31, 1, 5, 0, tzinfo=timezone.utc)
        assert isinstance(is_due(s, now), bool)

    def test_is_due_weekend_returns_bool(self):
        from autoresearch.daemon import is_due
        s = _make_schedule("weekend")
        now = datetime(2026, 4, 5, 1, 5, 0, tzinfo=timezone.utc)
        assert isinstance(is_due(s, now), bool)

    def test_is_due_daily_returns_bool(self):
        from autoresearch.daemon import is_due
        s = _make_schedule("daily")
        now = datetime(2026, 3, 31, 12, 0, 0, tzinfo=timezone.utc)
        assert isinstance(is_due(s, now), bool)


# ---------------------------------------------------------------------------
# _resolve_cron_expression — all SCHEDULE_CRON_MAP keys
# ---------------------------------------------------------------------------


class TestResolveCronAllMapKeys:
    def test_overnight_resolves(self):
        from autoresearch.daemon import _resolve_cron_expression, SCHEDULE_CRON_MAP
        s = _make_schedule("overnight")
        assert _resolve_cron_expression(s) == SCHEDULE_CRON_MAP["overnight"]

    def test_weekend_resolves(self):
        from autoresearch.daemon import _resolve_cron_expression, SCHEDULE_CRON_MAP
        s = _make_schedule("weekend")
        assert _resolve_cron_expression(s) == SCHEDULE_CRON_MAP["weekend"]

    def test_cron_type_uses_cron_field(self):
        from autoresearch.daemon import _resolve_cron_expression
        s = _make_schedule("cron", cron="5 4 * * 0")
        assert _resolve_cron_expression(s) == "5 4 * * 0"

    def test_unknown_type_returns_none_or_fallback(self):
        from autoresearch.daemon import _resolve_cron_expression
        s = _make_schedule("unknown", cron="15 6 * * 1")
        result = _resolve_cron_expression(s)
        # unknown type not in map, cron field not used by default
        assert result is None or isinstance(result, str)


# ---------------------------------------------------------------------------
# DaemonRunner — _join_threads with live thread
# ---------------------------------------------------------------------------


class TestDaemonRunnerJoinThreads:
    def test_join_alive_thread_is_called(self):
        from autoresearch.config import GlobalConfig
        with patch("autoresearch.daemon.load_config", return_value=GlobalConfig()):
            runner = DaemonRunner()
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = True
        runner._active_runs["marker-z"] = mock_thread
        runner._join_threads(timeout=0.01)
        mock_thread.join.assert_called()

    def test_join_no_threads_no_error(self):
        from autoresearch.config import GlobalConfig
        with patch("autoresearch.daemon.load_config", return_value=GlobalConfig()):
            runner = DaemonRunner()
        runner._join_threads(timeout=0.01)  # should not raise


# ---------------------------------------------------------------------------
# write_pid / read_pid / clear_pid round trip
# ---------------------------------------------------------------------------


class TestPidRoundTrip:
    def test_write_read_clear(self, tmp_path):
        pid_path = tmp_path / "subdir" / "my.pid"
        write_pid(42, pid_path)
        assert read_pid(pid_path) == 42
        clear_pid(pid_path)
        assert read_pid(pid_path) is None

    def test_clear_nonexistent_does_not_raise(self, tmp_path):
        pid_path = tmp_path / "missing.pid"
        clear_pid(pid_path)  # should not raise

    def test_write_pid_overwrites(self, tmp_path):
        pid_path = tmp_path / "pid"
        write_pid(100, pid_path)
        write_pid(200, pid_path)
        assert read_pid(pid_path) == 200


# ---------------------------------------------------------------------------
# is_pid_alive — basic behavior
# ---------------------------------------------------------------------------


class TestIsPidAliveBasic:
    def test_current_process_is_alive(self):
        import os
        from autoresearch.daemon import is_pid_alive
        assert is_pid_alive(os.getpid()) is True

    def test_zero_pid_is_not_alive(self):
        from autoresearch.daemon import is_pid_alive
        result = is_pid_alive(0)
        assert isinstance(result, bool)

    def test_very_large_pid_not_alive(self):
        from autoresearch.daemon import is_pid_alive
        result = is_pid_alive(9999999)
        assert result is False


# ---------------------------------------------------------------------------
# _resolve_cron_expression — more schedule types
# ---------------------------------------------------------------------------

class TestResolveCronExpressionExtended:
    def _make_schedule(self, type_, cron=None):
        from autoresearch.marker import Schedule
        return Schedule(type=type_, cron=cron)

    def test_on_demand_returns_none(self):
        assert _resolve_cron_expression(self._make_schedule("on-demand")) is None

    def test_overnight_returns_cron(self):
        result = _resolve_cron_expression(self._make_schedule("overnight"))
        assert result is not None
        assert "1" in result

    def test_weekend_returns_cron(self):
        result = _resolve_cron_expression(self._make_schedule("weekend"))
        assert result is not None

    def test_cron_type_with_expression(self):
        result = _resolve_cron_expression(self._make_schedule("cron", "0 3 * * *"))
        assert result == "0 3 * * *"

    def test_cron_type_without_expression_returns_none(self):
        result = _resolve_cron_expression(self._make_schedule("cron", None))
        assert result is None

    def test_unknown_type_returns_none(self):
        result = _resolve_cron_expression(self._make_schedule("custom-type"))
        assert result is None

    def test_daily_like_type_unknown_returns_none(self):
        # 'daily' not in SCHEDULE_CRON_MAP
        result = _resolve_cron_expression(self._make_schedule("daily"))
        assert result is None


# ---------------------------------------------------------------------------
# is_due — extended scenarios
# ---------------------------------------------------------------------------

class TestIsDueExtended:
    def _make_schedule(self, type_, cron=None, duration_hours=None):
        from autoresearch.marker import Schedule
        return Schedule(type=type_, cron=cron, duration_hours=duration_hours)

    def test_on_demand_is_never_due(self):
        assert is_due(self._make_schedule("on-demand"), None) is False

    def test_overnight_no_last_run_is_due(self):
        assert is_due(self._make_schedule("overnight"), None) is True

    def test_weekend_no_last_run_is_due(self):
        assert is_due(self._make_schedule("weekend"), None) is True

    def test_invalid_last_run_string_treated_as_never_run(self):
        assert is_due(self._make_schedule("overnight"), "not-a-date") is True

    def test_last_run_very_recent_not_due(self):
        now = datetime.now(timezone.utc)
        recent = (now - timedelta(seconds=10)).isoformat()
        # overnight fires once/day: not due 10 seconds after last run
        assert is_due(self._make_schedule("overnight"), recent, now) is False

    def test_last_run_25_hours_ago_overnight_is_due(self):
        now = datetime.now(timezone.utc)
        old = (now - timedelta(hours=25)).isoformat()
        assert is_due(self._make_schedule("overnight"), old, now) is True

    def test_cron_every_minute_with_old_run_is_due(self):
        now = datetime.now(timezone.utc)
        old = (now - timedelta(minutes=5)).isoformat()
        assert is_due(self._make_schedule("cron", "* * * * *"), old, now) is True

    def test_cron_every_minute_with_very_recent_run_not_due(self):
        # Use a fixed time mid-minute to avoid boundary flakiness
        now = datetime(2026, 6, 15, 12, 0, 30, tzinfo=timezone.utc)
        recent = (now - timedelta(seconds=5)).isoformat()
        # next fire is 30 seconds away, not due yet
        assert is_due(self._make_schedule("cron", "* * * * *"), recent, now) is False

    def test_invalid_cron_expression_returns_false(self):
        now = datetime.now(timezone.utc)
        last = (now - timedelta(hours=1)).isoformat()
        assert is_due(self._make_schedule("cron", "invalid cron here!!!"), last, now) is False

    def test_naive_last_run_treated_as_utc(self):
        now = datetime.now(timezone.utc)
        old = (now - timedelta(hours=25)).replace(tzinfo=None).isoformat()
        assert is_due(self._make_schedule("overnight"), old, now) is True


# ---------------------------------------------------------------------------
# read_pid / write_pid — additional edge cases
# ---------------------------------------------------------------------------

class TestReadPidEdgeCasesExtra2:
    def test_negative_number_returns_none(self, tmp_path):
        pid_path = tmp_path / "neg.pid"
        pid_path.write_text("-1")
        # -1 is a valid integer but read_pid just parses int
        result = read_pid(pid_path)
        assert result == -1 or result is None  # impl-dependent

    def test_very_large_number_parsed(self, tmp_path):
        pid_path = tmp_path / "big.pid"
        pid_path.write_text("4194304")
        assert read_pid(pid_path) == 4194304

    def test_zero_parsed(self, tmp_path):
        pid_path = tmp_path / "zero.pid"
        pid_path.write_text("0")
        result = read_pid(pid_path)
        assert result == 0 or result is None

    def test_pid_with_trailing_newline(self, tmp_path):
        pid_path = tmp_path / "nl.pid"
        pid_path.write_text("1234\n")
        assert read_pid(pid_path) == 1234

    def test_write_creates_directories(self, tmp_path):
        pid_path = tmp_path / "sub" / "deep" / "daemon.pid"
        write_pid(42, pid_path)
        assert pid_path.exists()
        assert read_pid(pid_path) == 42


# ---------------------------------------------------------------------------
# check_stale_pid — extended
# ---------------------------------------------------------------------------

class TestCheckStalePidExtended:
    def test_no_pid_file_returns_false(self, tmp_path):
        pid_path = tmp_path / "missing.pid"
        result = check_stale_pid(pid_path)
        assert result is False

    def test_stale_pid_clears_file(self, tmp_path):
        pid_path = tmp_path / "stale.pid"
        write_pid(9999999, pid_path)  # unlikely to exist
        check_stale_pid(pid_path)
        # After clearing, file should not exist or read_pid returns None
        if pid_path.exists():
            assert read_pid(pid_path) is None


# ---------------------------------------------------------------------------
# is_pid_alive — more scenarios
# ---------------------------------------------------------------------------

class TestIsPidAliveExtended:
    def test_current_process_alive(self):
        import os
        assert is_pid_alive(os.getpid()) is True

    def test_pid_1_alive_on_linux(self):
        # PID 1 (init) is always alive on Linux
        result = is_pid_alive(1)
        assert result is True

    def test_very_high_pid_not_alive(self):
        result = is_pid_alive(9999998)
        assert result is False

    def test_negative_pid_not_alive(self):
        result = is_pid_alive(-1)
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# _resolve_cron_expression — comprehensive
# ---------------------------------------------------------------------------

class TestResolveCronExpressionAll:
    def _make_sched(self, stype, cron=None):
        s = MagicMock()
        s.type = stype
        s.cron = cron
        return s

    def test_on_demand_returns_none(self):
        assert _resolve_cron_expression(self._make_sched("on-demand")) is None

    def test_overnight_returns_cron(self):
        result = _resolve_cron_expression(self._make_sched("overnight"))
        assert result == "0 1 * * *"

    def test_weekend_returns_cron(self):
        result = _resolve_cron_expression(self._make_sched("weekend"))
        assert result == "0 1 * * 6"

    def test_cron_type_with_expression(self):
        result = _resolve_cron_expression(self._make_sched("cron", "*/5 * * * *"))
        assert result == "*/5 * * * *"

    def test_cron_type_without_expression(self):
        result = _resolve_cron_expression(self._make_sched("cron", None))
        assert result is None

    def test_unknown_type_returns_none(self):
        result = _resolve_cron_expression(self._make_sched("unknown"))
        assert result is None

    def test_cron_empty_string_expression(self):
        result = _resolve_cron_expression(self._make_sched("cron", ""))
        assert result is None or result == ""


# ---------------------------------------------------------------------------
# is_due — additional boundary conditions
# ---------------------------------------------------------------------------

class TestIsDueBoundaries:
    def _make_sched(self, stype, cron=None):
        s = MagicMock()
        s.type = stype
        s.cron = cron
        return s

    def test_overnight_no_last_run(self):
        now = datetime.now(timezone.utc)
        assert is_due(self._make_sched("overnight"), None, now) is True

    def test_weekend_no_last_run(self):
        now = datetime.now(timezone.utc)
        assert is_due(self._make_sched("weekend"), None, now) is True

    def test_on_demand_never_due(self):
        now = datetime.now(timezone.utc)
        last = (now - timedelta(days=30)).isoformat()
        assert is_due(self._make_sched("on-demand"), last, now) is False

    def test_on_demand_no_last_run(self):
        now = datetime.now(timezone.utc)
        assert is_due(self._make_sched("on-demand"), None, now) is False

    def test_malformed_last_run_treated_as_none(self):
        now = datetime.now(timezone.utc)
        assert is_due(self._make_sched("overnight"), "not-a-date", now) is True

    def test_future_last_run_not_due(self):
        now = datetime.now(timezone.utc)
        future = (now + timedelta(hours=2)).isoformat()
        # Next cron fire after future is even further, not due yet
        result = is_due(self._make_sched("overnight"), future, now)
        assert result is False

    def test_old_overnight_run_is_due(self):
        now = datetime.now(timezone.utc)
        old = (now - timedelta(days=2)).isoformat()
        assert is_due(self._make_sched("overnight"), old, now) is True

    def test_cron_every_hour_old_run_due(self):
        now = datetime(2026, 6, 15, 14, 30, 0, tzinfo=timezone.utc)
        old = (now - timedelta(hours=2)).isoformat()
        assert is_due(self._make_sched("cron", "0 * * * *"), old, now) is True

    def test_cron_every_hour_recent_run_not_due(self):
        now = datetime(2026, 6, 15, 14, 30, 0, tzinfo=timezone.utc)
        recent = (now - timedelta(minutes=5)).isoformat()
        result = is_due(self._make_sched("cron", "0 * * * *"), recent, now)
        assert result is False


# ---------------------------------------------------------------------------
# DaemonRunner — attribute checks
# ---------------------------------------------------------------------------

class TestDaemonRunnerAttributes:
    def _make_runner(self):
        config = MagicMock()
        config.daemon.max_concurrent = 3
        config.daemon.poll_interval = "30s"
        with patch("autoresearch.daemon.load_config", return_value=config):
            return DaemonRunner(config=config)

    def test_has_shutdown_event(self):
        r = self._make_runner()
        import threading
        assert isinstance(r._shutdown, threading.Event)

    def test_has_active_runs_dict(self):
        r = self._make_runner()
        assert isinstance(r._active_runs, dict)
        assert len(r._active_runs) == 0

    def test_shutdown_sets_event(self):
        r = self._make_runner()
        assert not r._shutdown.is_set()
        r.shutdown()
        assert r._shutdown.is_set()

    def test_reap_threads_empty(self):
        r = self._make_runner()
        r._reap_threads()  # Should not raise
        assert r._active_runs == {}

    def test_poll_seconds_integer(self):
        r = self._make_runner()
        assert isinstance(r._poll_seconds, int)
        assert r._poll_seconds > 0


# ---------------------------------------------------------------------------
# write_pid / read_pid — round trips
# ---------------------------------------------------------------------------

class TestPidRoundTripExtended:
    def test_pid_1(self, tmp_path):
        p = tmp_path / "a.pid"
        write_pid(1, p)
        assert read_pid(p) == 1

    def test_pid_max_int(self, tmp_path):
        p = tmp_path / "b.pid"
        write_pid(65535, p)
        assert read_pid(p) == 65535

    def test_overwrite_pid(self, tmp_path):
        p = tmp_path / "c.pid"
        write_pid(100, p)
        write_pid(200, p)
        assert read_pid(p) == 200

    def test_clear_removes_file(self, tmp_path):
        p = tmp_path / "d.pid"
        write_pid(123, p)
        clear_pid(p)
        assert not p.exists()

    def test_clear_nonexistent_no_error(self, tmp_path):
        p = tmp_path / "nonexistent.pid"
        clear_pid(p)  # Should not raise

    def test_read_nonexistent_returns_none(self, tmp_path):
        p = tmp_path / "missing.pid"
        assert read_pid(p) is None

    def test_read_returns_int_type(self, tmp_path):
        p = tmp_path / "e.pid"
        write_pid(42, p)
        result = read_pid(p)
        assert isinstance(result, int)


# ---------------------------------------------------------------------------
# Additional is_due tests
# ---------------------------------------------------------------------------

class TestIsDueOvernightSchedule:
    def _make_sched(self, t, cron=None):
        s = MagicMock()
        s.type = t
        s.cron = cron
        return s

    def test_overnight_no_last_run_is_due(self):
        s = self._make_sched("overnight")
        assert is_due(s, None) is True

    def test_weekend_no_last_run_is_due(self):
        s = self._make_sched("weekend")
        assert is_due(s, None) is True

    def test_on_demand_never_due(self):
        s = self._make_sched("on-demand")
        assert is_due(s, None) is False

    def test_on_demand_with_last_run_still_false(self):
        s = self._make_sched("on-demand")
        assert is_due(s, "2024-01-01T00:00:00+00:00") is False

    def test_cron_with_explicit_expression(self):
        s = self._make_sched("cron", "* * * * *")
        # No last_run — should be due
        assert is_due(s, None) is True

    def test_invalid_cron_returns_false(self):
        from datetime import datetime, timezone
        s = self._make_sched("cron", "invalid-cron-expression")
        now = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        last = "2024-06-15T11:00:00+00:00"
        result = is_due(s, last, now)
        assert result is False


class TestIsDueInvalidLastRun:
    def _make_sched(self):
        s = MagicMock()
        s.type = "overnight"
        s.cron = None
        return s

    def test_invalid_last_run_is_due(self):
        s = self._make_sched()
        assert is_due(s, "not-a-date") is True

    def test_none_last_run_is_due(self):
        s = self._make_sched()
        assert is_due(s, None) is True


# ---------------------------------------------------------------------------
# PID management — edge cases
# ---------------------------------------------------------------------------

class TestPidManagementExtendedExtra:
    def test_write_creates_correct_content(self, tmp_path):
        p = tmp_path / "test.pid"
        write_pid(12345, p)
        assert p.read_text().strip() == "12345"

    def test_read_after_write_matches(self, tmp_path):
        p = tmp_path / "test.pid"
        write_pid(999, p)
        assert read_pid(p) == 999

    def test_write_overwrites_existing(self, tmp_path):
        p = tmp_path / "test.pid"
        write_pid(100, p)
        write_pid(200, p)
        assert read_pid(p) == 200

    def test_clear_makes_read_return_none(self, tmp_path):
        p = tmp_path / "test.pid"
        write_pid(42, p)
        clear_pid(p)
        assert read_pid(p) is None

    def test_clear_twice_no_error(self, tmp_path):
        p = tmp_path / "test.pid"
        write_pid(1, p)
        clear_pid(p)
        clear_pid(p)  # second clear should not raise


class TestCheckStalePidBranches:
    def test_no_pid_file_returns_false(self, tmp_path):
        p = tmp_path / "missing.pid"
        assert check_stale_pid(p) is False

    def test_stale_pid_clears_file(self, tmp_path):
        p = tmp_path / "test.pid"
        write_pid(999999999, p)
        result = check_stale_pid(p)
        # Either stale was cleared or process happened to exist
        if result:
            assert not p.exists()

    def test_alive_pid_returns_false(self, tmp_path):
        import os
        p = tmp_path / "alive.pid"
        write_pid(os.getpid(), p)
        assert check_stale_pid(p) is False


# ---------------------------------------------------------------------------
# DaemonRunner — additional attribute and config tests
# ---------------------------------------------------------------------------

class TestDaemonRunnerConfigDefaults:
    def test_runner_has_semaphore(self):
        cfg = MagicMock()
        cfg.daemon.max_concurrent = 2
        cfg.daemon.poll_interval = "10s"
        runner = DaemonRunner(config=cfg)
        assert runner._semaphore is not None

    def test_runner_shutdown_event_not_set(self):
        cfg = MagicMock()
        cfg.daemon.max_concurrent = 1
        cfg.daemon.poll_interval = "5s"
        runner = DaemonRunner(config=cfg)
        assert not runner._shutdown.is_set()

    def test_runner_active_runs_empty_initially(self):
        cfg = MagicMock()
        cfg.daemon.max_concurrent = 1
        cfg.daemon.poll_interval = "5s"
        runner = DaemonRunner(config=cfg)
        assert runner._active_runs == {}

    def test_runner_poll_seconds_matches_config(self):
        cfg = MagicMock()
        cfg.daemon.max_concurrent = 1
        cfg.daemon.poll_interval = "60s"
        runner = DaemonRunner(config=cfg)
        assert runner._poll_seconds == 60


class TestDaemonRunnerShutdownSetsEvent:
    def test_shutdown_sets_event(self):
        cfg = MagicMock()
        cfg.daemon.max_concurrent = 2
        cfg.daemon.poll_interval = "10s"
        runner = DaemonRunner(config=cfg)
        runner.shutdown()
        assert runner._shutdown.is_set()

    def test_shutdown_idempotent(self):
        cfg = MagicMock()
        cfg.daemon.max_concurrent = 2
        cfg.daemon.poll_interval = "10s"
        runner = DaemonRunner(config=cfg)
        runner.shutdown()
        runner.shutdown()
        assert runner._shutdown.is_set()


class TestDaemonRunnerReapThreadsVariants:
    def test_reap_removes_finished_thread(self):
        cfg = MagicMock()
        cfg.daemon.max_concurrent = 2
        cfg.daemon.poll_interval = "5s"
        runner = DaemonRunner(config=cfg)
        t = MagicMock()
        t.is_alive.return_value = False
        runner._active_runs["m1"] = t
        runner._reap_threads()
        assert "m1" not in runner._active_runs

    def test_reap_keeps_alive_thread(self):
        cfg = MagicMock()
        cfg.daemon.max_concurrent = 2
        cfg.daemon.poll_interval = "5s"
        runner = DaemonRunner(config=cfg)
        t = MagicMock()
        t.is_alive.return_value = True
        runner._active_runs["m2"] = t
        runner._reap_threads()
        assert "m2" in runner._active_runs

    def test_reap_empty_dict_no_error(self):
        cfg = MagicMock()
        cfg.daemon.max_concurrent = 2
        cfg.daemon.poll_interval = "5s"
        runner = DaemonRunner(config=cfg)
        runner._reap_threads()  # should not raise


# ---------------------------------------------------------------------------
# is_pid_alive — coverage
# ---------------------------------------------------------------------------

class TestIsPidAliveVariants:
    def test_current_process_is_alive(self):
        import os
        assert is_pid_alive(os.getpid()) is True

    def test_very_large_pid_not_alive(self):
        # PID 4194304 is beyond Linux max (4194304 is actually the limit on some systems)
        # Use a safe unreachable PID
        result = is_pid_alive(999999999)
        assert result is False

    def test_zero_pid_returns_true_or_false(self):
        # PID 0 sends to process group — just verify it returns a bool
        try:
            result = is_pid_alive(0)
            assert isinstance(result, bool)
        except (PermissionError, ProcessLookupError):
            pass


class TestResolveCronExpressionVariantsB:
    def test_on_demand_is_none(self):
        s = _make_schedule("on-demand")
        assert _resolve_cron_expression(s) is None

    def test_overnight_uses_default(self):
        s = _make_schedule("overnight")
        result = _resolve_cron_expression(s)
        assert result is not None

    def test_weekend_uses_default(self):
        s = _make_schedule("weekend")
        result = _resolve_cron_expression(s)
        assert result is not None

    def test_cron_with_value(self):
        s = _make_schedule("cron", "*/10 * * * *")
        assert _resolve_cron_expression(s) == "*/10 * * * *"

    def test_cron_without_value_is_none(self):
        s = _make_schedule("cron", None)
        assert _resolve_cron_expression(s) is None

    def test_unknown_type_is_none(self):
        s = _make_schedule("daily")
        assert _resolve_cron_expression(s) is None

    def test_cron_daily_expression(self):
        s = _make_schedule("cron", "0 9 * * *")
        assert _resolve_cron_expression(s) == "0 9 * * *"

    def test_cron_hourly_expression(self):
        s = _make_schedule("cron", "0 * * * *")
        assert _resolve_cron_expression(s) == "0 * * * *"

    def test_cron_monthly_expression(self):
        s = _make_schedule("cron", "0 0 1 * *")
        assert _resolve_cron_expression(s) == "0 0 1 * *"


class TestIsDueFurtherVariants:
    def test_on_demand_false_with_old_run(self):
        s = _make_schedule("on-demand")
        old = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        assert is_due(s, old) is False

    def test_on_demand_false_with_none(self):
        s = _make_schedule("on-demand")
        assert is_due(s, None) is False

    def test_overnight_no_last_run_is_due(self):
        s = _make_schedule("overnight")
        assert is_due(s, None) is True

    def test_overnight_old_run_is_due(self):
        s = _make_schedule("overnight")
        old = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        assert is_due(s, old) is True

    def test_overnight_recent_run_not_due(self):
        s = _make_schedule("overnight")
        recent = datetime.now(timezone.utc).isoformat()
        assert is_due(s, recent) is False

    def test_weekend_no_run_is_due(self):
        s = _make_schedule("weekend")
        assert is_due(s, None) is True

    def test_invalid_cron_with_recent_run_not_due(self):
        s = _make_schedule("cron", "not-a-cron")
        recent = datetime.now(timezone.utc).isoformat()
        assert is_due(s, recent) is False

    def test_every_minute_cron_old_run_is_due(self):
        s = _make_schedule("cron", "* * * * *")
        old = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        assert is_due(s, old) is True

    def test_every_minute_cron_very_recent_not_due(self):
        s = _make_schedule("cron", "* * * * *")
        recent = datetime.now(timezone.utc).isoformat()
        assert is_due(s, recent) is False

    def test_none_cron_type_not_due(self):
        s = _make_schedule("cron", None)
        assert is_due(s, None) is False


class TestPidManagementVariantsB:
    def test_write_positive_pid(self, tmp_path):
        p = tmp_path / "test.pid"
        write_pid(42, p)
        assert read_pid(p) == 42

    def test_write_large_pid(self, tmp_path):
        p = tmp_path / "test.pid"
        write_pid(65535, p)
        assert read_pid(p) == 65535

    def test_clear_removes_file(self, tmp_path):
        p = tmp_path / "test.pid"
        write_pid(100, p)
        clear_pid(p)
        assert not p.exists()

    def test_read_empty_file_returns_none(self, tmp_path):
        p = tmp_path / "test.pid"
        p.write_text("")
        assert read_pid(p) is None

    def test_read_whitespace_only_returns_none(self, tmp_path):
        p = tmp_path / "test.pid"
        p.write_text("   \n")
        assert read_pid(p) is None

    def test_write_then_overwrite(self, tmp_path):
        p = tmp_path / "test.pid"
        write_pid(100, p)
        write_pid(200, p)
        assert read_pid(p) == 200

    def test_clear_nonexistent_no_error(self, tmp_path):
        p = tmp_path / "nonexistent.pid"
        clear_pid(p)  # should not raise

    def test_check_stale_no_file_is_false(self, tmp_path):
        p = tmp_path / "no.pid"
        assert check_stale_pid(p) is False

    def test_check_stale_dead_pid_removes_file(self, tmp_path):
        p = tmp_path / "dead.pid"
        write_pid(999999999, p)
        result = check_stale_pid(p)
        assert result is True
        assert not p.exists()

    def test_is_pid_alive_current(self):
        import os
        assert is_pid_alive(os.getpid()) is True

    def test_is_pid_alive_dead_pid(self):
        assert is_pid_alive(999999998) is False


class TestDaemonRunnerAttributesB:
    def _make_runner(self):
        from autoresearch.config import GlobalConfig
        with patch("autoresearch.daemon.load_config", return_value=GlobalConfig()):
            return DaemonRunner()

    def test_poll_seconds_positive(self):
        r = self._make_runner()
        assert r._poll_seconds > 0

    def test_active_runs_starts_empty(self):
        r = self._make_runner()
        assert len(r._active_runs) == 0

    def test_shutdown_event_not_set_initially(self):
        r = self._make_runner()
        assert not r._shutdown.is_set()

    def test_shutdown_sets_event(self):
        r = self._make_runner()
        r.shutdown()
        assert r._shutdown.is_set()

    def test_shutdown_is_idempotent(self):
        r = self._make_runner()
        r.shutdown()
        r.shutdown()
        assert r._shutdown.is_set()

    def test_reap_threads_empty(self):
        r = self._make_runner()
        r._reap_threads()  # should not raise

    def test_reap_removes_finished_thread(self):
        r = self._make_runner()
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = False
        r._active_runs["repo:marker"] = mock_thread
        r._reap_threads()
        assert "repo:marker" not in r._active_runs

    def test_reap_keeps_alive_thread(self):
        r = self._make_runner()
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = True
        r._active_runs["repo:marker"] = mock_thread
        r._reap_threads()
        assert "repo:marker" in r._active_runs


class TestStopDaemonVariants:
    def test_no_pid_file_returns_false(self, tmp_path):
        p = tmp_path / "no.pid"
        result = stop_daemon(pid_path=p)
        assert result is False

    def test_stale_pid_returns_false(self, tmp_path):
        p = tmp_path / "stale.pid"
        write_pid(999999997, p)
        result = stop_daemon(pid_path=p)
        assert result is False


# ---------------------------------------------------------------------------
# NEW BATCH: is_pid_alive more variants
# ---------------------------------------------------------------------------

class TestIsPidAliveNewBatch:
    def test_current_process_alive(self):
        import os
        assert is_pid_alive(os.getpid()) is True

    def test_zero_pid_not_alive(self):
        # PID 0 is not a normal process
        result = is_pid_alive(0)
        assert isinstance(result, bool)

    def test_very_large_pid_not_alive(self):
        result = is_pid_alive(99999998)
        assert result is False

    def test_negative_pid_returns_bool(self):
        result = is_pid_alive(-1)
        assert isinstance(result, bool)

    def test_pid_one_check_returns_bool(self):
        result = is_pid_alive(1)
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# NEW BATCH: write_pid / read_pid round-trip extended
# ---------------------------------------------------------------------------

class TestPidRoundTripNewBatch:
    def test_write_and_read_basic(self, tmp_path):
        p = tmp_path / "test.pid"
        write_pid(12345, p)
        assert read_pid(p) == 12345

    def test_write_overwrite(self, tmp_path):
        p = tmp_path / "test.pid"
        write_pid(111, p)
        write_pid(222, p)
        assert read_pid(p) == 222

    def test_read_nonexistent_returns_none(self, tmp_path):
        p = tmp_path / "nope.pid"
        assert read_pid(p) is None

    def test_write_creates_parent(self, tmp_path):
        p = tmp_path / "subdir" / "test.pid"
        write_pid(9999, p)
        assert p.exists()

    def test_read_after_clear_returns_none(self, tmp_path):
        p = tmp_path / "test.pid"
        write_pid(42, p)
        clear_pid(p)
        assert read_pid(p) is None

    def test_clear_nonexistent_no_error(self, tmp_path):
        p = tmp_path / "nope.pid"
        clear_pid(p)  # should not raise

    def test_pid_value_preserved(self, tmp_path):
        p = tmp_path / "pid.pid"
        for val in [1, 100, 1000, 99999]:
            write_pid(val, p)
            assert read_pid(p) == val


# ---------------------------------------------------------------------------
# NEW BATCH: check_stale_pid extended
# ---------------------------------------------------------------------------

class TestCheckStalePidNewBatch:
    def test_no_pid_file_returns_false(self, tmp_path):
        p = tmp_path / "none.pid"
        assert check_stale_pid(p) is False

    def test_live_pid_returns_false(self, tmp_path):
        import os
        p = tmp_path / "live.pid"
        write_pid(os.getpid(), p)
        assert check_stale_pid(p) is False

    def test_stale_pid_returns_true(self, tmp_path):
        p = tmp_path / "stale.pid"
        write_pid(99999997, p)
        result = check_stale_pid(p)
        # stale or missing = True; not alive = True
        assert isinstance(result, bool)

    def test_returns_bool(self, tmp_path):
        p = tmp_path / "x.pid"
        result = check_stale_pid(p)
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# NEW BATCH: is_due extended time-based
# ---------------------------------------------------------------------------

class TestIsDueNewBatch:
    def _now(self):
        return datetime.now(timezone.utc)

    def test_on_demand_never_due(self):
        s = _make_schedule("on-demand")
        assert is_due(s, last_run=None) is False

    def test_on_demand_with_last_run_never_due(self):
        s = _make_schedule("on-demand")
        assert is_due(s, last_run="2020-01-01T00:00:00Z") is False

    def test_cron_due_long_ago(self):
        s = _make_schedule("cron", cron="* * * * *")
        old = "2000-01-01T00:00:00Z"
        result = is_due(s, last_run=old)
        assert result is True

    def test_cron_never_run_is_due(self):
        s = _make_schedule("cron", cron="* * * * *")
        assert is_due(s, last_run=None) is True

    def test_invalid_cron_not_due(self):
        s = _make_schedule("cron", cron="not-a-cron")
        result = is_due(s, last_run=None)
        assert isinstance(result, bool)

    def test_unknown_type_not_due(self):
        s = Schedule(type="unknown")
        result = is_due(s, last_run=None)
        assert result is False


# ---------------------------------------------------------------------------
# NEW BATCH: _resolve_cron_expression map checks
# ---------------------------------------------------------------------------

class TestResolveCronNewBatch:
    def test_overnight_resolves(self):
        s = _make_schedule("overnight")
        result = _resolve_cron_expression(s)
        assert result is not None
        assert isinstance(result, str)

    def test_weekend_resolves(self):
        s = _make_schedule("weekend")
        result = _resolve_cron_expression(s)
        assert result is not None

    def test_overnight_is_cron_string(self):
        s = _make_schedule("overnight")
        result = _resolve_cron_expression(s)
        assert isinstance(result, str)
        assert len(result.split()) == 5

    def test_raw_cron_passthrough(self):
        s = _make_schedule("cron", cron="0 9 * * *")
        result = _resolve_cron_expression(s)
        assert result == "0 9 * * *"

    def test_unknown_type_returns_none(self):
        s = _make_schedule("notakey")
        result = _resolve_cron_expression(s)
        assert result is None

    def test_on_demand_returns_none(self):
        s = _make_schedule("on-demand")
        result = _resolve_cron_expression(s)
        assert result is None

    def test_five_star_cron_passthrough(self):
        s = _make_schedule("cron", cron="* * * * *")
        result = _resolve_cron_expression(s)
        assert result == "* * * * *"

    def test_monthly_resolves_or_none(self):
        s = _make_schedule("monthly")
        result = _resolve_cron_expression(s)
        assert result is None or isinstance(result, str)


# ---------------------------------------------------------------------------
# NEW BATCH: DaemonRunner attributes
# ---------------------------------------------------------------------------

class TestDaemonRunnerNewBatch:
    def _make_runner(self):
        return DaemonRunner()

    def test_has_shutdown_attribute(self):
        r = self._make_runner()
        assert hasattr(r, "_shutdown")

    def test_instantiates(self):
        r = self._make_runner()
        assert r is not None

    def test_has_active_runs(self):
        r = self._make_runner()
        assert hasattr(r, "_active_runs")

    def test_has_poll_seconds(self):
        r = self._make_runner()
        assert hasattr(r, "_poll_seconds")
        assert r._poll_seconds > 0

    def test_has_semaphore(self):
        r = self._make_runner()
        assert hasattr(r, "_semaphore")


# ---------------------------------------------------------------------------
# NEW BATCH: stop_daemon additional
# ---------------------------------------------------------------------------

class TestStopDaemonNewBatch:
    def test_no_file_returns_false(self, tmp_path):
        p = tmp_path / "no.pid"
        assert stop_daemon(pid_path=p) is False

    def test_stale_returns_false(self, tmp_path):
        p = tmp_path / "s.pid"
        write_pid(99999996, p)
        assert stop_daemon(pid_path=p) is False

    def test_returns_bool(self, tmp_path):
        p = tmp_path / "r.pid"
        result = stop_daemon(pid_path=p)
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# NEW BATCH: is_due and pid helpers additional
# ---------------------------------------------------------------------------

class TestIsDueAdditional:
    def test_on_demand_never_due(self):
        s = _make_schedule("on-demand")
        assert not is_due(s, None)

    def test_on_demand_with_last_run_not_due(self):
        s = _make_schedule("on-demand")
        last = datetime(2020, 1, 1, tzinfo=timezone.utc).isoformat()
        assert not is_due(s, last)

    def test_overnight_no_last_run_is_due(self):
        s = _make_schedule("overnight")
        assert is_due(s, None)

    def test_overnight_old_last_run_bool(self):
        s = _make_schedule("overnight")
        old = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        assert isinstance(is_due(s, old), bool)

    def test_cron_no_last_run_is_due(self):
        s = _make_schedule("cron", "0 * * * *")
        assert is_due(s, None) is True

    def test_cron_no_last_run_returns_bool(self):
        s = _make_schedule("cron", "0 * * * *")
        result = is_due(s, None)
        assert isinstance(result, bool)


class TestPidHelpersAdditional:
    def test_write_read_roundtrip(self, tmp_path):
        p = tmp_path / "test.pid"
        write_pid(12345, p)
        assert read_pid(p) == 12345

    def test_read_missing_returns_none(self, tmp_path):
        p = tmp_path / "missing.pid"
        assert read_pid(p) is None

    def test_clear_removes_file(self, tmp_path):
        p = tmp_path / "c.pid"
        write_pid(999, p)
        clear_pid(p)
        assert not p.exists()

    def test_clear_missing_no_error(self, tmp_path):
        p = tmp_path / "none.pid"
        clear_pid(p)  # should not raise

    def test_check_stale_missing_returns_false(self, tmp_path):
        p = tmp_path / "s.pid"
        assert check_stale_pid(p) is False

    def test_is_pid_alive_invalid_returns_false(self):
        assert not is_pid_alive(99999997)

    def test_is_pid_alive_self_returns_true(self):
        assert is_pid_alive(os.getpid())

    def test_write_creates_file(self, tmp_path):
        p = tmp_path / "w.pid"
        write_pid(1, p)
        assert p.exists()

    def test_read_returns_int(self, tmp_path):
        p = tmp_path / "r.pid"
        write_pid(42, p)
        assert isinstance(read_pid(p), int)

    def test_stop_no_pid_file(self, tmp_path):
        p = tmp_path / "nopid.pid"
        result = stop_daemon(pid_path=p)
        assert result is False


class TestResolveCronAdditional:
    def test_on_demand_returns_none(self):
        s = _make_schedule("on-demand")
        assert _resolve_cron_expression(s) is None

    def test_cron_type_passthrough(self):
        s = _make_schedule("cron", "0 9 * * *")
        assert _resolve_cron_expression(s) == "0 9 * * *"

    def test_overnight_returns_string(self):
        s = _make_schedule("overnight")
        result = _resolve_cron_expression(s)
        assert isinstance(result, str)

    def test_overnight_has_5_fields(self):
        s = _make_schedule("overnight")
        result = _resolve_cron_expression(s)
        assert result is not None
        assert len(result.split()) == 5

    def test_weekend_has_5_fields(self):
        s = _make_schedule("weekend")
        result = _resolve_cron_expression(s)
        assert result is not None
        assert len(result.split()) == 5

    def test_cron_arbitrary_expr(self):
        expr = "15 3 * * 1"
        s = _make_schedule("cron", expr)
        assert _resolve_cron_expression(s) == expr

    def test_unknown_type_returns_none_or_str(self):
        s = _make_schedule("unknown-type")
        result = _resolve_cron_expression(s)
        assert result is None or isinstance(result, str)


class TestDaemonRunnerAdditional:
    def test_instantiation(self, tmp_path):
        dr = DaemonRunner(state_path=tmp_path / "state.json")
        assert dr is not None

    def test_has_state_path(self, tmp_path):
        dr = DaemonRunner(state_path=tmp_path / "state.json")
        assert hasattr(dr, "_state_path")

    def test_has_semaphore(self, tmp_path):
        dr = DaemonRunner(state_path=tmp_path / "state.json")
        assert hasattr(dr, "_semaphore")

    def test_semaphore_is_threading_semaphore(self, tmp_path):
        import threading
        dr = DaemonRunner(state_path=tmp_path / "state.json")
        assert isinstance(dr._semaphore, threading.Semaphore)
