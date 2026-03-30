"""Results management (.autoresearch/<marker>/results.tsv)."""

from __future__ import annotations

import csv
from pathlib import Path

from pydantic import BaseModel


RESULTS_DIR = ".autoresearch"
RESULTS_FILE = "results.tsv"
TSV_HEADER = ["commit", "metric", "guard", "status", "confidence", "description"]


class ExperimentResult(BaseModel):
    commit: str
    metric: float
    guard: str = "--"
    status: str
    confidence: str = "--"
    description: str


def ensure_results_dir(repo_path: Path, marker_name: str) -> Path:
    """Create .autoresearch/<marker>/ if needed. Return path."""
    results_dir = repo_path / RESULTS_DIR / marker_name
    results_dir.mkdir(parents=True, exist_ok=True)
    return results_dir


def _results_path(repo_path: Path, marker_name: str) -> Path:
    return repo_path / RESULTS_DIR / marker_name / RESULTS_FILE


def read_results(repo_path: Path, marker_name: str) -> list[ExperimentResult]:
    """Parse results.tsv. Return empty list if file missing."""
    path = _results_path(repo_path, marker_name)
    if not path.is_file():
        return []
    results = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            results.append(ExperimentResult(
                commit=row["commit"],
                metric=float(row["metric"]),
                guard=row["guard"],
                status=row["status"],
                confidence=row["confidence"],
                description=row["description"],
            ))
    return results


def append_result(repo_path: Path, marker_name: str, result: ExperimentResult) -> None:
    """Append a row to results.tsv. Create file with header if missing."""
    results_dir = ensure_results_dir(repo_path, marker_name)
    path = results_dir / RESULTS_FILE
    write_header = not path.is_file()
    with open(path, "a", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        if write_header:
            writer.writerow(TSV_HEADER)
        writer.writerow([
            result.commit,
            result.metric,
            result.guard,
            result.status,
            result.confidence,
            result.description,
        ])


def get_latest_metric(results: list[ExperimentResult]) -> float | None:
    """Return metric from last 'keep' result, or None."""
    for r in reversed(results):
        if r.status == "keep":
            return r.metric
    return None


def get_kept_metrics(results: list[ExperimentResult]) -> list[float]:
    """Return all metrics from 'keep' results, for confidence scoring."""
    return [r.metric for r in results if r.status == "keep"]
