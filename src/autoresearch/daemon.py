"""Daemon: schedule evaluation, PID management, background runner."""

from __future__ import annotations

import logging
import os
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from croniter import croniter

from autoresearch.config import AUTORESEARCH_DIR, load_config
from autoresearch.engine import EngineError, get_agent_runner, run_marker
from autoresearch.marker import MarkerStatus, find_marker_file, get_marker, load_markers
from autoresearch.state import (
    get_effective_status,
    get_tracked,
    load_state,
    save_state,
)
from autoresearch.utils import parse_duration

logger = logging.getLogger(__name__)

PID_PATH = AUTORESEARCH_DIR / "daemon.pid"
LOG_PATH = AUTORESEARCH_DIR / "daemon.log"

# ---------------------------------------------------------------------------
# Schedule evaluation
# ---------------------------------------------------------------------------

SCHEDULE_CRON_MAP = {
    "overnight": "0 1 * * *",
    "weekend": "0 1 * * 6",
}


def _resolve_cron_expression(schedule) -> str | None:
    """Map schedule type to a cron expression. Returns None for on-demand."""
    if schedule.type == "on-demand":
        return None
    if schedule.type == "cron" and schedule.cron:
        return schedule.cron
    return SCHEDULE_CRON_MAP.get(schedule.type)


def is_due(schedule, last_run: str | None, now: datetime | None = None) -> bool:
    """Check if a marker is due for execution based on its schedule."""
    cron_expr = _resolve_cron_expression(schedule)
    if cron_expr is None:
        return False

    now = now or datetime.now(timezone.utc)

    if last_run is None:
        return True

    try:
        last_run_dt = datetime.fromisoformat(last_run)
        if last_run_dt.tzinfo is None:
            last_run_dt = last_run_dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return True

    try:
        next_fire = croniter(cron_expr, last_run_dt).get_next(datetime)
        return now >= next_fire
    except (ValueError, KeyError):
        logger.warning("Invalid cron expression: %s", cron_expr)
        return False


# ---------------------------------------------------------------------------
# PID management
# ---------------------------------------------------------------------------


def write_pid(pid: int, pid_path: Path = PID_PATH) -> None:
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(str(pid))


def read_pid(pid_path: Path = PID_PATH) -> int | None:
    try:
        return int(pid_path.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def clear_pid(pid_path: Path = PID_PATH) -> None:
    pid_path.unlink(missing_ok=True)


def is_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # Process exists but owned by another user


def check_stale_pid(pid_path: Path = PID_PATH) -> bool:
    """Check for stale PID file. Cleans up if stale. Returns True if stale was cleared."""
    pid = read_pid(pid_path)
    if pid is None:
        return False
    if not is_pid_alive(pid):
        clear_pid(pid_path)
        return True
    return False


# ---------------------------------------------------------------------------
# DaemonRunner
# ---------------------------------------------------------------------------


class DaemonRunner:
    """Scheduler loop that polls tracked markers and runs them when due."""

    def __init__(self, config=None, state_path: Path | None = None):
        self._config = config or load_config()
        self._state_path = state_path
        self._shutdown = threading.Event()
        self._active_runs: dict[str, threading.Thread] = {}
        self._semaphore = threading.Semaphore(self._config.daemon.max_concurrent)
        self._poll_seconds = parse_duration(self._config.daemon.poll_interval)

    def run(self):
        """Main loop. Blocks until shutdown."""
        logger.info("Daemon started, polling every %ds", self._poll_seconds)
        while not self._shutdown.is_set():
            try:
                self._tick()
            except Exception:
                logger.exception("Error in daemon tick")
            self._shutdown.wait(timeout=self._poll_seconds)
        self._join_threads()
        logger.info("Daemon stopped")

    def _tick(self):
        """Single evaluation cycle."""
        state = load_state(self._state_path)
        self._reap_threads()

        now = datetime.now(timezone.utc)
        for tracked in state.markers:
            if tracked.id in self._active_runs:
                continue

            mf_path = find_marker_file(Path(tracked.repo_path))
            if not mf_path:
                continue
            try:
                mf = load_markers(mf_path)
            except Exception:
                continue
            marker = get_marker(mf, tracked.marker_name)
            if not marker:
                continue

            eff_status = get_effective_status(tracked, marker.status)
            if eff_status != MarkerStatus.ACTIVE:
                continue

            if not is_due(marker.schedule, tracked.last_run, now):
                continue

            if not self._semaphore.acquire(blocking=False):
                logger.debug("Max concurrent reached, deferring %s", tracked.id)
                break

            t = threading.Thread(
                target=self._run_marker_thread,
                args=(tracked, marker),
                daemon=True,
                name=f"marker-{tracked.id}",
            )
            self._active_runs[tracked.id] = t
            t.start()
            logger.info("Started run for %s", tracked.id)

    def _run_marker_thread(self, tracked, marker):
        """Execute a single marker in a thread."""
        try:
            state = load_state(self._state_path)
            t = get_tracked(state, tracked.id)
            if not t:
                return

            agent_runner = get_agent_runner(marker)
            result = run_marker(
                repo_path=Path(t.repo_path),
                marker=marker,
                state=state,
                tracked=t,
                agent_runner=agent_runner,
                state_path=self._state_path,
            )
            logger.info(
                "Completed %s: %d experiments, %d kept",
                tracked.id, result.experiments, result.kept,
            )
        except EngineError as e:
            logger.error("Engine error for %s: %s", tracked.id, e)
        except Exception:
            logger.exception("Unexpected error running %s", tracked.id)
        finally:
            self._semaphore.release()

    def _reap_threads(self):
        """Remove finished threads from active runs."""
        finished = [mid for mid, t in self._active_runs.items() if not t.is_alive()]
        for mid in finished:
            del self._active_runs[mid]

    def _join_threads(self, timeout: float = 30):
        """Wait for active threads to finish."""
        for mid, t in self._active_runs.items():
            logger.info("Waiting for %s to finish...", mid)
            t.join(timeout=timeout)

    def shutdown(self):
        self._shutdown.set()


# ---------------------------------------------------------------------------
# Daemonize + stop
# ---------------------------------------------------------------------------


def daemonize(
    log_path: Path = LOG_PATH,
    pid_path: Path = PID_PATH,
    config=None,
    state_path: Path | None = None,
) -> int:
    """Fork into a background daemon process. Returns daemon PID to parent."""
    if sys.platform == "win32":
        raise RuntimeError(
            "Daemon mode is not supported on Windows. "
            "Use 'autoresearch run -m <marker> --headless' with Task Scheduler instead."
        )

    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Create a pipe so the grandchild can report its PID back to the parent
    read_fd, write_fd = os.pipe()

    pid = os.fork()
    if pid > 0:
        # Parent: wait for first child to exit, then read grandchild PID from pipe
        os.close(write_fd)
        os.waitpid(pid, 0)
        data = os.read(read_fd, 32)
        os.close(read_fd)
        return int(data.decode().strip())

    # First child: new session
    os.close(read_fd)
    os.setsid()

    # Double-fork to prevent zombie
    pid2 = os.fork()
    if pid2 > 0:
        # First child: write grandchild PID to pipe and exit
        os.write(write_fd, str(pid2).encode())
        os.close(write_fd)
        os._exit(0)

    # Grandchild: the actual daemon
    os.close(write_fd)
    daemon_pid = os.getpid()
    write_pid(daemon_pid, pid_path)

    # Update state
    state = load_state(state_path)
    state.daemon.running = True
    state.daemon.pid = daemon_pid
    state.daemon.started_at = datetime.now(timezone.utc).isoformat()
    save_state(state, state_path)

    # Redirect stdin to /dev/null, stdout/stderr to log
    devnull = os.open(os.devnull, os.O_RDONLY)
    os.dup2(devnull, sys.stdin.fileno())
    os.close(devnull)

    log_fd = open(log_path, "a")
    os.dup2(log_fd.fileno(), sys.stdout.fileno())
    os.dup2(log_fd.fileno(), sys.stderr.fileno())

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        stream=log_fd,
        force=True,
    )

    runner = DaemonRunner(config=config, state_path=state_path)

    def _handle_signal(signum, frame):
        logger.info("Received signal %d, shutting down", signum)
        runner.shutdown()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    try:
        runner.run()
    finally:
        clear_pid(pid_path)
        state = load_state(state_path)
        state.daemon.running = False
        state.daemon.pid = None
        save_state(state, state_path)
        log_fd.close()

    os._exit(0)


def stop_daemon(pid_path: Path = PID_PATH, state_path: Path | None = None) -> bool:
    """Stop a running daemon. Returns True if stopped, False if nothing to stop."""
    stale = check_stale_pid(pid_path)
    if stale:
        # Reset state for stale daemon
        state = load_state(state_path)
        state.daemon.running = False
        state.daemon.pid = None
        save_state(state, state_path)

    pid = read_pid(pid_path)
    if pid is None:
        return False

    if not is_pid_alive(pid):
        clear_pid(pid_path)
        return False

    os.kill(pid, signal.SIGTERM)

    # Wait up to 10 seconds for process to exit
    stopped = False
    for _ in range(20):
        if not is_pid_alive(pid):
            stopped = True
            break
        time.sleep(0.5)

    if stopped:
        clear_pid(pid_path)
        state = load_state(state_path)
        state.daemon.running = False
        state.daemon.pid = None
        save_state(state, state_path)

    return stopped
