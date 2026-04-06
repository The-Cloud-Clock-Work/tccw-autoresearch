"""Marker schema and .autoresearch/config.yaml parser."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
import yaml
from pydantic import BaseModel, model_validator


MARKER_FILENAME = ".autoresearch.yaml"
CONFIG_DIR = ".autoresearch"
CONFIG_FILENAME = "config.yaml"


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
    issues_command: str | None = None


class Guard(BaseModel):
    command: str | None = None
    extract: str | None = None
    threshold: float | None = None
    rework_attempts: int = 2


class LoopConfig(BaseModel):
    """Deprecated — fields moved to AgentConfig. Kept for backward compat."""

    model: str = ""
    budget_per_experiment: str = ""
    max_experiments: int = 0
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


class AutoMerge(BaseModel):
    enabled: bool = False
    target_branch: str = "dev"
    gates: list[str] = ["security", "tests", "confidence"]
    security_command: str | None = None
    test_command: str | None = None
    min_confidence: float = 1.0
    push_to_remote: bool = False
    create_pr: bool = False
    snapshot_command: str | None = None
    restore_command: str | None = None
    notify: list[str] = []


class AgentConfig(BaseModel):
    name: str = "default"
    model: str = "sonnet"
    effort: str = "medium"
    permission_mode: str = "bypassPermissions"
    budget_per_experiment: str = "10m"
    max_experiments: int = 50
    max_cost: str | None = None
    allowed_tools: list[str] = []
    disallowed_tools: list[str] = []
    extra_flags: list[str] = []


class Marker(BaseModel):
    name: str
    description: str = ""
    status: MarkerStatus = MarkerStatus.ACTIVE
    target: Target
    metric: Metric
    guard: Guard = Guard()
    loop: LoopConfig = LoopConfig()
    escalation: Escalation = Escalation()
    schedule: Schedule = Schedule()
    results: ResultsConfig = ResultsConfig()
    agent: AgentConfig = AgentConfig()
    auto_merge: AutoMerge = AutoMerge()

    @model_validator(mode="after")
    def _migrate_loop_to_agent(self):
        """Backward compat: if loop has values, copy them to agent."""
        if self.loop.model and not self.agent.model:
            self.agent.model = self.loop.model
        if self.loop.budget_per_experiment:
            self.agent.budget_per_experiment = self.loop.budget_per_experiment
        if self.loop.max_experiments:
            self.agent.max_experiments = self.loop.max_experiments
        if self.loop.max_cost:
            self.agent.max_cost = self.loop.max_cost
        return self


class MarkerFile(BaseModel):
    markers: list[Marker]


def load_markers(path: Path) -> MarkerFile:
    """Read .autoresearch/config.yaml, validate, return typed MarkerFile."""
    with open(path) as f:
        data = yaml.safe_load(f)
    return MarkerFile.model_validate(data)


def find_marker_file(repo_path: Path) -> Path | None:
    """Search for marker config. Checks .autoresearch/config.yaml first, then .autoresearch.yaml (legacy)."""
    new_path = repo_path / CONFIG_DIR / CONFIG_FILENAME
    if new_path.is_file():
        return new_path
    legacy_path = repo_path / MARKER_FILENAME
    return legacy_path if legacy_path.is_file() else None


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
