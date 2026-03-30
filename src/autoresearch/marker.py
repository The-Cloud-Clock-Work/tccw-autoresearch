"""Marker schema and .autoresearch.yaml parser."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
import yaml
from pydantic import BaseModel


MARKER_FILENAME = ".autoresearch.yaml"


class MarkerStatus(str, Enum):
    ACTIVE = "active"
    SKIP = "skip"
    PAUSED = "paused"
    COMPLETED = "completed"
    NEEDS_HUMAN = "needs_human"


class MetricDirection(str, Enum):
    LOWER = "lower"
    HIGHER = "higher"


class Target(BaseModel):
    mutable: list[str]
    immutable: list[str] = []


class Metric(BaseModel):
    command: str
    extract: str
    direction: MetricDirection
    baseline: float
    target: float | None = None


class Guard(BaseModel):
    command: str | None = None
    extract: str | None = None
    threshold: float | None = None
    rework_attempts: int = 2


class LoopConfig(BaseModel):
    model: str = "sonnet"
    budget_per_experiment: str = "10m"
    max_experiments: int = 50
    max_cost: str | None = None


class Escalation(BaseModel):
    refine_after: int = 3
    pivot_after: int = 5
    search_after_pivots: int = 2
    halt_after_pivots: int = 3


class Schedule(BaseModel):
    type: str = "on-demand"
    cron: str | None = None
    duration_hours: int | None = None


class ResultsConfig(BaseModel):
    branch_prefix: str = "autoresearch"
    notify: list[str] = []
    auto_merge: bool = False


class Marker(BaseModel):
    name: str
    description: str = ""
    status: MarkerStatus = MarkerStatus.ACTIVE
    target: Target
    metric: Metric
    guard: Guard = Guard()
    loop: LoopConfig
    escalation: Escalation = Escalation()
    schedule: Schedule = Schedule()
    results: ResultsConfig = ResultsConfig()


class MarkerFile(BaseModel):
    markers: list[Marker]


def load_markers(path: Path) -> MarkerFile:
    """Read .autoresearch.yaml, validate, return typed MarkerFile."""
    with open(path) as f:
        data = yaml.safe_load(f)
    return MarkerFile.model_validate(data)


def find_marker_file(repo_path: Path) -> Path | None:
    """Search for .autoresearch.yaml in repo root. Return path or None."""
    candidate = repo_path / MARKER_FILENAME
    return candidate if candidate.is_file() else None


def get_marker(marker_file: MarkerFile, name: str) -> Marker | None:
    """Find a specific marker by name."""
    for m in marker_file.markers:
        if m.name == name:
            return m
    return None


def resolve_marker_id(marker_id: str) -> tuple[str, str]:
    """Parse 'repo_name:marker_name' into (repo_name, marker_name).

    Raises ValueError if format is invalid.
    """
    if ":" not in marker_id:
        raise ValueError(f"Invalid marker ID '{marker_id}': expected 'repo_name:marker_name'")
    parts = marker_id.split(":", 1)
    return parts[0], parts[1]
