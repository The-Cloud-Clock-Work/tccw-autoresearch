"""Tests for finalization module."""

from __future__ import annotations

import os
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from autoresearch.finalize import (
    _find_merge_base,
    _unique_final_branch,
    finalize_marker,
    merge_finalized,
)
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


class TestUniqueFinalBranch:
    def test_returns_base_when_available(self, git_repo):
        repo_path, env, commits = git_repo
        name = _unique_final_branch(repo_path, "totally-new-branch-xyz")
        assert name == "totally-new-branch-xyz"

    def test_increments_suffix_when_base_exists(self, git_repo):
        repo_path, env, commits = git_repo
        # Create the base branch so it conflicts
        subprocess.run(
            ["git", "checkout", "-b", "conflict-branch"],
            cwd=repo_path, env=env, capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "checkout", "autoresearch/test-marker-mar30"],
            cwd=repo_path, env=env, capture_output=True, check=True,
        )
        name = _unique_final_branch(repo_path, "conflict-branch")
        assert name == "conflict-branch-2"

    def test_increments_again_when_dash_2_exists(self, git_repo):
        repo_path, env, commits = git_repo
        for suffix in ("x-branch", "x-branch-2"):
            subprocess.run(
                ["git", "checkout", "-b", suffix],
                cwd=repo_path, env=env, capture_output=True, check=True,
            )
        subprocess.run(
            ["git", "checkout", "autoresearch/test-marker-mar30"],
            cwd=repo_path, env=env, capture_output=True, check=True,
        )
        name = _unique_final_branch(repo_path, "x-branch")
        assert name == "x-branch-3"

    def test_raises_when_all_names_taken(self, git_repo):
        """_unique_final_branch raises GitError when all 100 candidates exist (line 29)."""
        repo_path, env, commits = git_repo
        base = "autoresearch/marker-final-1"
        all_names = {base} | {f"{base}-{i}" for i in range(2, 100)}
        mock_result = MagicMock()
        mock_result.stdout = "\n".join(all_names)

        with patch("autoresearch.finalize._run_git", return_value=mock_result):
            with pytest.raises(GitError, match="Could not find unique branch name"):
                _unique_final_branch(repo_path, base)


class TestFindMergeBase:
    def test_uses_merge_base_when_available(self, git_repo):
        repo_path, env, commits = git_repo
        result = _find_merge_base(repo_path, "main")
        assert len(result) == 40  # full SHA

    def test_fallback_to_head_minus_1(self, git_repo):
        repo_path, env, commits = git_repo
        call_log = []

        def side_effect(args, **kwargs):
            call_log.append(args[0] if args else "")
            if args[0] == "merge-base":
                raise GitError("no common ancestor")
            m = MagicMock()
            m.stdout = "aabbccdd" * 5  # 40 chars
            return m

        with patch("autoresearch.finalize._run_git", side_effect=side_effect):
            result = _find_merge_base(repo_path, "main")
        assert result == "aabbccdd" * 5
        assert "merge-base" in call_log
        assert "rev-parse" in call_log

    def test_fallback_to_head_when_no_parent(self, git_repo):
        repo_path, env, commits = git_repo

        def side_effect(args, **kwargs):
            cmd = args[0] if args else ""
            if cmd == "merge-base":
                raise GitError("no ancestor")
            # HEAD~1 fails (initial commit has no parent)
            if cmd == "rev-parse" and len(args) > 1 and "HEAD~1" in " ".join(args):
                raise GitError("bad revision HEAD~1")
            m = MagicMock()
            m.stdout = "deadbeef" * 5
            return m

        with patch("autoresearch.finalize._run_git", side_effect=side_effect):
            result = _find_merge_base(repo_path, "main")
        assert result == "deadbeef" * 5


class TestFinalizeMarkerEdgeCases:
    def test_unique_branch_used_when_base_taken(self, git_repo):
        """Exercises _unique_final_branch loop via finalize_marker."""
        repo_path, env, commits = git_repo
        # Pre-create the first branch name that finalize_marker would choose
        subprocess.run(
            ["git", "checkout", "-b", "autoresearch/test-marker-final-1"],
            cwd=repo_path, env=env, capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "checkout", "autoresearch/test-marker-mar30"],
            cwd=repo_path, env=env, capture_output=True, check=True,
        )
        results = [
            ExperimentResult(commit=commits[0], metric=10.0, guard="pass", status="keep", confidence="--", description="opt A"),
        ]
        branches = finalize_marker(
            repo_path, "test-marker", results,
            source_branch="autoresearch/test-marker-mar30",
        )
        assert len(branches) == 1
        assert branches[0]["branch"].endswith("-2")

    def test_squash_when_multiple_commits_same_description(self, git_repo):
        """Exercises squash path (len(applied) > 1)."""
        repo_path, env, commits = git_repo
        results = [
            ExperimentResult(commit=commits[0], metric=10.0, guard="pass", status="keep", confidence="--", description="same desc"),
            ExperimentResult(commit=commits[1], metric=12.0, guard="pass", status="keep", confidence="--", description="Same Desc"),
        ]
        branches = finalize_marker(
            repo_path, "test-marker", results,
            source_branch="autoresearch/test-marker-mar30",
        )
        # Both commits share same normalized description → one group, one branch
        assert len(branches) == 1
        assert branches[0]["metric_delta"] == pytest.approx(2.0)

    def test_metric_delta_none_for_single_metric(self, git_repo):
        """Single commit in group yields metric_delta=None."""
        repo_path, env, commits = git_repo
        results = [
            ExperimentResult(commit=commits[0], metric=10.0, guard="pass", status="keep", confidence="--", description="solo"),
        ]
        branches = finalize_marker(
            repo_path, "test-marker", results,
            source_branch="autoresearch/test-marker-mar30",
        )
        assert branches[0]["metric_delta"] is None

    def test_cherry_pick_failure_skipped(self, git_repo):
        """When cherry-pick fails, that commit is skipped (abort called)."""
        repo_path, env, commits = git_repo

        cherry_pick_calls = []

        def side_effect(args, **kwargs):
            cmd_str = " ".join(args)
            if "cherry-pick" in cmd_str and "--abort" not in cmd_str:
                cherry_pick_calls.append(args)
                raise GitError("conflict")
            if "cherry-pick" in cmd_str and "--abort" in cmd_str:
                cherry_pick_calls.append(args)
                raise GitError("nothing to abort")  # tests inner except
            # All other git calls pass through
            import subprocess as sp
            result = sp.run(
                ["git"] + args,
                cwd=kwargs.get("cwd", repo_path),
                capture_output=True, text=True,
            )
            m = MagicMock()
            m.stdout = result.stdout
            m.returncode = result.returncode
            if result.returncode != 0:
                raise GitError(result.stderr)
            return m

        results = [
            ExperimentResult(commit=commits[0], metric=10.0, guard="pass", status="keep", confidence="--", description="will-fail"),
        ]
        with patch("autoresearch.finalize._run_git", side_effect=side_effect):
            branches = finalize_marker(
                repo_path, "test-marker", results,
                source_branch="autoresearch/test-marker-mar30",
            )
        # All cherry-picks failed → branch cleaned up, no branches returned
        assert branches == []

    def test_checkout_dash_fallback_when_no_source_branch(self, git_repo):
        """Without source_branch, returns to previous branch via checkout -."""
        repo_path, env, commits = git_repo
        results = [
            ExperimentResult(commit=commits[0], metric=10.0, guard="pass", status="keep", confidence="--", description="no-src"),
        ]
        # No source_branch passed
        branches = finalize_marker(repo_path, "test-marker", results)
        assert len(branches) == 1

    def test_outer_git_error_during_squash_triggers_cleanup(self, git_repo):
        """GitError during squash triggers outer except handler (lines 115-121)."""
        repo_path, env, commits = git_repo

        orig_run_git = None
        import autoresearch.finalize as fin_mod
        orig_run_git = fin_mod._run_git

        def selective_mock(args, cwd=None):
            if args[0] == "reset" and "--soft" in args:
                raise GitError("reset failed")
            return orig_run_git(args, cwd=cwd)

        results = [
            ExperimentResult(commit=commits[0], metric=10.0, guard="pass", status="keep", confidence="--", description="squash-me"),
            ExperimentResult(commit=commits[1], metric=11.0, guard="pass", status="keep", confidence="--", description="squash-me"),
        ]
        with patch("autoresearch.finalize._run_git", side_effect=selective_mock):
            branches = finalize_marker(
                repo_path, "test-marker", results,
                source_branch="autoresearch/test-marker-mar30",
            )
        # Outer handler caught the error, branch should be cleaned up
        assert branches == []

    def test_checkout_source_branch_fails_falls_back_to_dash(self, git_repo):
        """When checkout source_branch fails, falls back to checkout - (lines 127-128)."""
        repo_path, env, commits = git_repo

        import autoresearch.finalize as fin_mod
        orig_run_git = fin_mod._run_git

        def selective_mock(args, cwd=None):
            # Fail the final checkout of the source branch
            if args[0] == "checkout" and len(args) == 2 and args[1] == "my-source-branch":
                raise GitError("branch not found")
            return orig_run_git(args, cwd=cwd)

        results = [
            ExperimentResult(commit=commits[0], metric=10.0, guard="pass", status="keep", confidence="--", description="test-cb"),
        ]
        with patch("autoresearch.finalize._run_git", side_effect=selective_mock):
            branches = finalize_marker(
                repo_path, "test-marker", results,
                source_branch="my-source-branch",
            )
        assert len(branches) == 1


class TestFinalizeCleanupGitErrorSuppressed:
    """Cover finalize.py lines 120-121: inner GitError during cleanup is silently ignored."""

    def test_cleanup_git_error_suppressed_when_cherry_pick_fails(self, tmp_path):
        """When cherry-pick fails AND cleanup (checkout/branch -D) also raises GitError, it is suppressed."""
        from autoresearch.finalize import finalize_marker
        from autoresearch.results import ExperimentResult
        from autoresearch.worktree import GitError

        call_log = []

        def selective_mock(args, cwd=None):
            call_log.append(list(args))
            # Fail cherry-pick to trigger outer except
            if args[0] == "cherry-pick" and "--abort" not in args:
                raise GitError("cherry-pick conflict")
            # Also fail cleanup checkout to trigger inner except (lines 120-121)
            if args[0] == "checkout" and len(args) == 2:
                raise GitError("checkout failed during cleanup")
            # Allow cherry-pick --abort and branch -D through (or also fail)
            if args[0] == "branch" and "-D" in args:
                raise GitError("branch -D failed during cleanup")
            # Allow other calls (checkout-b, etc.)
            return MagicMock(stdout="", returncode=0)

        results = [
            ExperimentResult(commit="abc1234", metric=5.0, guard="pass", status="keep", confidence="--", description="test-cleanup"),
        ]
        with patch("autoresearch.finalize._run_git", side_effect=selective_mock):
            branches = finalize_marker(
                tmp_path, "test-marker", results,
                source_branch=None,
            )
        assert branches == []

    def test_cleanup_git_error_suppressed_with_source_branch(self, tmp_path):
        """Inner GitError during cleanup is suppressed even with source_branch set."""
        from autoresearch.finalize import finalize_marker
        from autoresearch.results import ExperimentResult
        from autoresearch.worktree import GitError

        def selective_mock(args, cwd=None):
            if args[0] == "cherry-pick" and "--abort" not in args:
                raise GitError("cherry-pick conflict")
            if args[0] == "checkout" and len(args) == 2 and args[1] != "-":
                raise GitError("checkout fails")
            if args[0] == "branch" and "-D" in args:
                raise GitError("branch delete fails")
            return MagicMock(stdout="", returncode=0)

        results = [
            ExperimentResult(commit="def5678", metric=3.0, guard="pass", status="keep", confidence="--", description="cleanup-test"),
        ]
        with patch("autoresearch.finalize._run_git", side_effect=selective_mock):
            branches = finalize_marker(
                tmp_path, "test-marker", results,
                source_branch="autoresearch/test-marker-mar30",
            )
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
