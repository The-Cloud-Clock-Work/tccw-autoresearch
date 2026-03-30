"""Finalization: cherry-pick kept commits into clean branches, merge."""

from __future__ import annotations

import logging
from pathlib import Path

from autoresearch.results import ExperimentResult
from autoresearch.worktree import GitError, _run_git

logger = logging.getLogger(__name__)


def _normalize_description(desc: str) -> str:
    """Normalize description for grouping similar changes."""
    return desc.strip().lower()


def _unique_final_branch(repo_path: Path, base_name: str) -> str:
    """Find a branch name that doesn't exist yet."""
    result = _run_git(["branch", "--list"], cwd=repo_path)
    existing = {b.strip().lstrip("* ") for b in result.stdout.splitlines()}
    if base_name not in existing:
        return base_name
    for i in range(2, 100):
        candidate = f"{base_name}-{i}"
        if candidate not in existing:
            return candidate
    raise GitError(f"Could not find unique branch name for {base_name}")


def _find_merge_base(repo_path: Path, target_branch: str) -> str:
    """Find merge-base between HEAD and target branch, with fallbacks."""
    try:
        result = _run_git(["merge-base", "HEAD", target_branch], cwd=repo_path)
        return result.stdout.strip()
    except GitError:
        pass
    try:
        result = _run_git(["rev-parse", "HEAD~1"], cwd=repo_path)
        return result.stdout.strip()
    except GitError:
        result = _run_git(["rev-parse", "HEAD"], cwd=repo_path)
        return result.stdout.strip()


def finalize_marker(
    repo_path: Path,
    marker_name: str,
    results: list[ExperimentResult],
    source_branch: str | None = None,
    target_branch: str = "main",
) -> list[dict]:
    """Cherry-pick kept commits into clean finalization branches.

    Returns list of dicts with 'branch', 'commits', 'description', 'metric_delta'.
    Does NOT delete the original experimental branch.
    """
    kept = [r for r in results if r.status == "keep" and r.commit and r.commit != "--"]
    if not kept:
        return []

    # Group by normalized description
    groups: dict[str, list[ExperimentResult]] = {}
    for r in kept:
        key = _normalize_description(r.description) if r.description else f"commit-{r.commit}"
        groups.setdefault(key, []).append(r)

    merge_base = _find_merge_base(repo_path, target_branch)

    created_branches = []
    for i, (desc_key, group_results) in enumerate(groups.items(), 1):
        branch_base = f"autoresearch/{marker_name}-final-{i}"
        branch_name = _unique_final_branch(repo_path, branch_base)

        _run_git(["checkout", "-b", branch_name, merge_base], cwd=repo_path)

        try:
            commits = [r.commit for r in group_results]
            applied = []
            for commit in commits:
                try:
                    _run_git(["cherry-pick", commit], cwd=repo_path)
                    applied.append(commit)
                except GitError as e:
                    logger.warning("Cherry-pick failed for %s: %s", commit, e)
                    try:
                        _run_git(["cherry-pick", "--abort"], cwd=repo_path)
                    except GitError:
                        pass
                    continue

            if not applied:
                # All cherry-picks failed — clean up branch
                _run_git(["checkout", source_branch or "-"], cwd=repo_path)
                _run_git(["branch", "-D", branch_name], cwd=repo_path)
                continue

            # Squash into single commit if multiple
            if len(applied) > 1:
                _run_git(["reset", "--soft", merge_base], cwd=repo_path)
                combined_desc = group_results[0].description or desc_key
                _run_git(["commit", "-m", f"[autoresearch] {combined_desc}"], cwd=repo_path)

            metrics = [r.metric for r in group_results if r.metric is not None]
            # Metric spread across grouped commits (max - min); None if single commit
            metric_delta = max(metrics) - min(metrics) if len(metrics) > 1 else None

            created_branches.append({
                "branch": branch_name,
                "commits": applied,
                "description": group_results[0].description or desc_key,
                "metric_delta": metric_delta,
            })
        except GitError as e:
            logger.error("Failed to create finalization branch %s: %s", branch_name, e)
            try:
                _run_git(["checkout", source_branch or "-"], cwd=repo_path)
                _run_git(["branch", "-D", branch_name], cwd=repo_path)
            except GitError:
                pass

    # Return to original branch
    if source_branch:
        try:
            _run_git(["checkout", source_branch], cwd=repo_path)
        except GitError:
            _run_git(["checkout", "-"], cwd=repo_path)

    return created_branches


def merge_finalized(
    repo_path: Path,
    branch: str,
    target: str = "main",
) -> str:
    """Merge a finalized branch into target. Returns merge commit hash."""
    _run_git(["checkout", target], cwd=repo_path)
    _run_git(["merge", "--no-ff", branch, "-m", f"Merge {branch}"], cwd=repo_path)
    result = _run_git(["rev-parse", "HEAD"], cwd=repo_path)
    return result.stdout.strip()
