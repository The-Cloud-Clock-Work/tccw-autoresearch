"""Tests for finalization module."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from autoresearch.finalize import finalize_marker, merge_finalized
from autoresearch.results import ExperimentResult
from autoresearch.worktree import GitError


@pytest.fixture
def git_repo(tmp_path):
    """Create a minimal git repo with an initial commit."""
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@test.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@test.com",
        "HOME": str(tmp_path),
    }
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, env=env, capture_output=True, check=True)
    # Initial commit
    (tmp_path / "readme.txt").write_text("init")
    subprocess.run(["git", "add", "."], cwd=tmp_path, env=env, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=tmp_path, env=env, capture_output=True, check=True)

    # Create a branch with some commits
    subprocess.run(["git", "checkout", "-b", "autoresearch/test-marker-mar30"], cwd=tmp_path, env=env, capture_output=True, check=True)

    commits = []
    for i in range(3):
        (tmp_path / f"file{i}.py").write_text(f"content {i}")
        subprocess.run(["git", "add", "."], cwd=tmp_path, env=env, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", f"experiment {i}"], cwd=tmp_path, env=env, capture_output=True, check=True)
        result = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=tmp_path, env=env, capture_output=True, text=True, check=True)
        commits.append(result.stdout.strip())

    return tmp_path, env, commits


class TestFinalizeMarker:
    def test_no_kept_results(self, tmp_path):
        results = [
            ExperimentResult(commit="abc1234", metric=10.0, guard="pass", status="discard", confidence="--", description="test"),
        ]
        branches = finalize_marker(tmp_path, "test-marker", results)
        assert branches == []

    def test_empty_results(self, tmp_path):
        branches = finalize_marker(tmp_path, "test-marker", [])
        assert branches == []

    def test_finalize_single_kept(self, git_repo):
        repo_path, env, commits = git_repo
        results = [
            ExperimentResult(commit=commits[0], metric=10.0, guard="pass", status="keep", confidence="--", description="optimization A"),
        ]
        branches = finalize_marker(
            repo_path, "test-marker", results,
            source_branch="autoresearch/test-marker-mar30",
        )
        assert len(branches) == 1
        assert "final-1" in branches[0]["branch"]
        assert branches[0]["description"] == "optimization A"

    def test_finalize_groups_by_description(self, git_repo):
        repo_path, env, commits = git_repo
        results = [
            ExperimentResult(commit=commits[0], metric=10.0, guard="pass", status="keep", confidence="--", description="optimization A"),
            ExperimentResult(commit=commits[1], metric=15.0, guard="pass", status="keep", confidence="--", description="optimization B"),
        ]
        branches = finalize_marker(
            repo_path, "test-marker", results,
            source_branch="autoresearch/test-marker-mar30",
        )
        # Two different descriptions = two branches
        assert len(branches) == 2

    def test_does_not_delete_original_branch(self, git_repo):
        repo_path, env, commits = git_repo
        results = [
            ExperimentResult(commit=commits[0], metric=10.0, guard="pass", status="keep", confidence="--", description="test"),
        ]
        finalize_marker(
            repo_path, "test-marker", results,
            source_branch="autoresearch/test-marker-mar30",
        )
        # Original branch should still exist
        result = subprocess.run(
            ["git", "branch", "--list", "autoresearch/test-marker-mar30"],
            cwd=repo_path, capture_output=True, text=True,
        )
        assert "autoresearch/test-marker-mar30" in result.stdout

    def test_skips_baseline_commits(self, tmp_path):
        results = [
            ExperimentResult(commit="--", metric=10.0, guard="--", status="keep", confidence="--", description="baseline"),
        ]
        branches = finalize_marker(tmp_path, "test-marker", results)
        assert branches == []


class TestMergeFinalized:
    def test_merge_into_main(self, git_repo):
        repo_path, env, commits = git_repo
        # We're on autoresearch/test-marker-mar30, merge into main
        commit = merge_finalized(repo_path, "autoresearch/test-marker-mar30", "main")
        assert len(commit) == 40  # full SHA

        # Verify we're on main
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=repo_path, capture_output=True, text=True,
        )
        assert result.stdout.strip() == "main"

    def test_merge_nonexistent_branch(self, git_repo):
        repo_path, env, commits = git_repo
        with pytest.raises(GitError):
            merge_finalized(repo_path, "nonexistent-branch", "main")
