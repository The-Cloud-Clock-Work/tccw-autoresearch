"""Git worktree isolation for autoresearch markers."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from tempfile import mkdtemp


class GitError(Exception):
    """Raised when a git subprocess fails."""


@dataclass
class WorktreeInfo:
    """Info about a created worktree."""

    path: Path
    branch: str
    base_commit: str


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run a git command, raising GitError on failure."""
    try:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise GitError(f"git {' '.join(args)} failed: {e.stderr.strip()}") from e


def _unique_branch(repo_path: Path, base_name: str) -> str:
    """Find a branch name that doesn't exist yet."""
    result = _run_git(["branch", "--list"], repo_path)
    existing = {line.strip().lstrip("*+ ") for line in result.stdout.splitlines()}
    if base_name not in existing:
        return base_name
    for i in range(2, 100):
        candidate = f"{base_name}-{i}"
        if candidate not in existing:
            return candidate
    raise GitError(f"Could not find unique branch name for {base_name}")


def create_worktree(
    repo_path: Path,
    marker_name: str,
    branch_prefix: str = "autoresearch",
    worktree_base: Path | None = None,
) -> WorktreeInfo:
    """Create a git worktree with a new branch for a marker.

    Args:
        repo_path: Path to the main repository.
        marker_name: Marker name (used in branch and directory naming).
        branch_prefix: Branch prefix (default: "autoresearch").
        worktree_base: Directory to create worktree in. Uses temp dir if None.

    Returns:
        WorktreeInfo with path, branch name, and base commit.
    """
    date_suffix = date.today().strftime("%b%d").lower()
    base_branch = f"{branch_prefix}/{marker_name}-{date_suffix}"
    branch = _unique_branch(repo_path, base_branch)

    base_commit = git_head_short(repo_path)

    created_temp = False
    if worktree_base is None:
        worktree_base = Path(mkdtemp(prefix="autoresearch-"))
        created_temp = True
    wt_path = worktree_base / marker_name
    wt_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        _run_git(["worktree", "add", "-b", branch, str(wt_path)], repo_path)
    except GitError:
        if created_temp and worktree_base.exists():
            import shutil
            shutil.rmtree(worktree_base, ignore_errors=True)
        raise

    return WorktreeInfo(path=wt_path, branch=branch, base_commit=base_commit)


def remove_worktree(repo_path: Path, worktree_path: Path) -> None:
    """Remove a worktree and prune."""
    _run_git(["worktree", "remove", "--force", str(worktree_path)], repo_path)
    _run_git(["worktree", "prune"], repo_path)


def git_commit(worktree_path: Path, message: str) -> str:
    """Stage all changes and commit. Returns short hash, or empty string if nothing to commit."""
    _run_git(["add", "-A"], worktree_path)

    # Check if there are staged changes (exit 0 = clean, 1 = dirty)
    try:
        _run_git(["diff", "--cached", "--quiet"], worktree_path)
        return ""  # Clean — nothing to commit
    except GitError:
        pass  # Dirty — proceed to commit

    _run_git(["commit", "-m", message], worktree_path)
    return git_head_short(worktree_path)


def git_reset_hard(worktree_path: Path, commit: str) -> None:
    """Hard reset worktree to a specific commit."""
    _run_git(["reset", "--hard", commit], worktree_path)


def git_head_short(path: Path) -> str:
    """Return 7-character short hash of HEAD."""
    result = _run_git(["rev-parse", "--short=7", "HEAD"], path)
    return result.stdout.strip()
