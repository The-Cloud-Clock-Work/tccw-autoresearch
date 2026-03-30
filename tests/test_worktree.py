"""Tests for worktree.py — git worktree isolation."""

import subprocess
from pathlib import Path

import pytest

from autoresearch.worktree import (
    GitError,
    WorktreeInfo,
    create_worktree,
    git_commit,
    git_head_short,
    git_reset_hard,
    remove_worktree,
)


@pytest.fixture
def git_repo(tmp_path):
    """Create a minimal git repo with one committed file."""
    repo = tmp_path / "test-repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "main.py").write_text("x = 1\n")
    env = {
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@test.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@test.com",
        "HOME": str(tmp_path),
    }
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, env=env)
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True, env=env)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=repo,
        check=True,
        capture_output=True,
        env=env,
    )
    return repo


class TestCreateWorktree:
    def test_creates_worktree_and_branch(self, git_repo, tmp_path):
        wt_base = tmp_path / "worktrees"
        wt_base.mkdir()
        info = create_worktree(git_repo, "auth-flow", worktree_base=wt_base)

        assert isinstance(info, WorktreeInfo)
        assert info.path.exists()
        assert (info.path / "src" / "main.py").exists()
        assert "autoresearch/auth-flow-" in info.branch
        assert len(info.base_commit) == 7

    def test_branch_naming_has_date(self, git_repo, tmp_path):
        wt_base = tmp_path / "worktrees"
        wt_base.mkdir()
        info = create_worktree(git_repo, "my-marker", worktree_base=wt_base)

        from datetime import date

        expected_suffix = date.today().strftime("%b%d").lower()
        assert info.branch == f"autoresearch/my-marker-{expected_suffix}"

    def test_custom_branch_prefix(self, git_repo, tmp_path):
        wt_base = tmp_path / "worktrees"
        wt_base.mkdir()
        info = create_worktree(
            git_repo, "test", branch_prefix="custom", worktree_base=wt_base
        )
        assert info.branch.startswith("custom/test-")

    def test_collision_appends_counter(self, git_repo, tmp_path):
        wt_base = tmp_path / "worktrees"
        wt_base.mkdir()
        info1 = create_worktree(git_repo, "dup", worktree_base=wt_base / "a")
        info2 = create_worktree(git_repo, "dup", worktree_base=wt_base / "b")

        assert info1.branch != info2.branch
        assert "-2" in info2.branch

    def test_temp_dir_when_no_base(self, git_repo):
        info = create_worktree(git_repo, "temp-test")
        assert info.path.exists()
        remove_worktree(git_repo, info.path)


class TestGitCommit:
    def test_commit_returns_hash(self, git_repo, tmp_path):
        wt_base = tmp_path / "worktrees"
        wt_base.mkdir()
        info = create_worktree(git_repo, "commit-test", worktree_base=wt_base)

        (info.path / "src" / "main.py").write_text("x = 2\n")
        short_hash = git_commit(info.path, "update x to 2")

        assert len(short_hash) == 7
        assert short_hash != info.base_commit

    def test_empty_commit_returns_empty(self, git_repo, tmp_path):
        wt_base = tmp_path / "worktrees"
        wt_base.mkdir()
        info = create_worktree(git_repo, "no-change", worktree_base=wt_base)

        result = git_commit(info.path, "nothing changed")
        assert result == ""


class TestGitResetHard:
    def test_reset_reverts_changes(self, git_repo, tmp_path):
        wt_base = tmp_path / "worktrees"
        wt_base.mkdir()
        info = create_worktree(git_repo, "reset-test", worktree_base=wt_base)
        original = git_head_short(info.path)

        (info.path / "src" / "main.py").write_text("x = 99\n")
        git_commit(info.path, "change x")

        git_reset_hard(info.path, original)
        content = (info.path / "src" / "main.py").read_text()
        assert content == "x = 1\n"


class TestRemoveWorktree:
    def test_removes_worktree(self, git_repo, tmp_path):
        wt_base = tmp_path / "worktrees"
        wt_base.mkdir()
        info = create_worktree(git_repo, "remove-test", worktree_base=wt_base)
        assert info.path.exists()

        remove_worktree(git_repo, info.path)
        assert not info.path.exists()


class TestGitHeadShort:
    def test_returns_7_chars(self, git_repo):
        h = git_head_short(git_repo)
        assert len(h) == 7

    def test_not_a_repo_raises(self, tmp_path):
        with pytest.raises(GitError):
            git_head_short(tmp_path)
