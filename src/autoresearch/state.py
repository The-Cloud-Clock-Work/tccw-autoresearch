"""State management (~/.autoresearch/state.json)."""

from __future__ import annotations

import fcntl
import json
from pathlib import Path

from pydantic import BaseModel

from autoresearch.config import AUTORESEARCH_DIR
from autoresearch.marker import Marker, MarkerStatus


STATE_PATH = AUTORESEARCH_DIR / "state.json"


class TrackedMarker(BaseModel):
    id: str
    repo_path: str
    repo_name: str
    marker_name: str
    status_override: MarkerStatus | None = None
    last_run: str | None = None
    last_run_experiments: int = 0
    last_run_kept: int = 0
    last_run_discarded: int = 0
    branch: str | None = None
    baseline: float | None = None
    current: float | None = None
    worktree_path: str | None = None


class DaemonState(BaseModel):
    running: bool = False
    pid: int | None = None
    started_at: str | None = None


class AppState(BaseModel):
    markers: list[TrackedMarker] = []
    daemon: DaemonState = DaemonState()


def load_state(state_path: Path | None = None) -> AppState:
    """Read state.json. Return empty state if file missing."""
    path = state_path or STATE_PATH
    if not path.is_file():
        return AppState()
    with open(path) as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        data = json.load(f)
        fcntl.flock(f, fcntl.LOCK_UN)
    return AppState.model_validate(data)


def save_state(state: AppState, state_path: Path | None = None) -> None:
    """Write state to disk with exclusive file lock."""
    path = state_path or STATE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        json.dump(state.model_dump(), f, indent=2)
        f.flush()
        fcntl.flock(f, fcntl.LOCK_UN)


def update_state(update_fn, state_path: Path | None = None) -> AppState:
    """Atomic read-modify-write on state.json.

    Holds an exclusive lock for the entire operation so concurrent
    writers (engine finishing + CLI adding markers) don't clobber
    each other. update_fn receives the AppState and modifies it
    in place.
    """
    path = state_path or STATE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    # Open for read+write, create if missing
    if not path.is_file():
        path.write_text("{}")

    with open(path, "r+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            data = {}
        state = AppState.model_validate(data)
        update_fn(state)
        f.seek(0)
        f.truncate()
        json.dump(state.model_dump(), f, indent=2)
        f.flush()
        fcntl.flock(f, fcntl.LOCK_UN)

    return state


def derive_marker_id(repo_path: Path, marker_name: str, state: AppState | None = None) -> str:
    """Build 'repo_name:marker_name' with conflict handling.

    Per SPECS 1.5: if two repos share a directory name but different paths,
    use the full resolved path as repo_name fallback.
    """
    resolved = repo_path.resolve()
    repo_name = resolved.name

    if state is not None:
        for tracked in state.markers:
            tracked_name = Path(tracked.repo_path).name
            if tracked_name == repo_name and Path(tracked.repo_path).resolve() != resolved:
                repo_name = str(resolved)
                break

    return f"{repo_name}:{marker_name}"


def track_marker(state: AppState, repo_path: Path, marker: Marker) -> TrackedMarker:
    """Add a marker to tracked list. Derives repo_name from path."""
    marker_id = derive_marker_id(repo_path, marker.name, state)
    existing = get_tracked(state, marker_id)
    if existing:
        return existing
    resolved = repo_path.resolve()
    tracked = TrackedMarker(
        id=marker_id,
        repo_path=str(resolved),
        repo_name=resolved.name,
        marker_name=marker.name,
        baseline=marker.metric.baseline,
    )
    state.markers.append(tracked)
    return tracked


def untrack_marker(state: AppState, marker_id: str) -> bool:
    """Remove marker from tracked list. Returns True if found."""
    for i, m in enumerate(state.markers):
        if m.id == marker_id:
            state.markers.pop(i)
            return True
    return False


def get_tracked(state: AppState, marker_id: str) -> TrackedMarker | None:
    """Find tracked marker by ID."""
    for m in state.markers:
        if m.id == marker_id:
            return m
    return None


def get_effective_status(tracked: TrackedMarker, yaml_status: MarkerStatus) -> MarkerStatus:
    """Resolve status: local override takes precedence over YAML."""
    if tracked.status_override is not None:
        return tracked.status_override
    return yaml_status
