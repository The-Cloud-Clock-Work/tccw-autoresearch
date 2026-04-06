"""Integration Test 3: Full worktree create → edit → commit → reset → cleanup."""

import subprocess

from autoresearch.worktree import (
    create_worktree,
    git_commit,
    git_head_short,
    git_reset_hard,
    remove_worktree,
)


class TestWorktreeLifecycle:
    def test_create_worktree(self, git_repo):
        info = create_worktree(git_repo, "integration-test")
        assert info.path.is_dir()
        assert info.branch.startswith("autoresearch/integration-test")
        assert len(info.base_commit) == 7
        remove_worktree(git_repo, info.path)

    def test_edit_and_commit(self, git_repo):
        info = create_worktree(git_repo, "edit-test")
        test_file = info.path / "new_file.py"
        test_file.write_text("x = 1\n")

        commit_hash = git_commit(info.path, "add new file")
        assert commit_hash != ""
        assert len(commit_hash) == 7

        # Verify file exists in worktree
        assert test_file.is_file()
        remove_worktree(git_repo, info.path)

    def test_reset_reverts_changes(self, git_repo):
        info = create_worktree(git_repo, "reset-test")
        test_file = info.path / "will_revert.py"
        test_file.write_text("x = 1\n")
        git_commit(info.path, "add file")

        git_reset_hard(info.path, info.base_commit)
        assert not test_file.exists()
        remove_worktree(git_repo, info.path)

    def test_remove_worktree_cleans_up(self, git_repo):
        info = create_worktree(git_repo, "cleanup-test")
        wt_path = info.path
        assert wt_path.is_dir()

        remove_worktree(git_repo, wt_path)
        assert not wt_path.is_dir()

    def test_head_short_returns_hash(self, git_repo):
        h = git_head_short(git_repo)
        assert len(h) == 7
        assert all(c in "0123456789abcdef" for c in h)

    def test_no_changes_returns_empty_commit(self, git_repo):
        info = create_worktree(git_repo, "no-change-test")
        result = git_commit(info.path, "nothing changed")
        assert result == ""
        remove_worktree(git_repo, info.path)

    def test_multiple_worktrees_coexist(self, git_repo):
        info1 = create_worktree(git_repo, "multi-1")
        info2 = create_worktree(git_repo, "multi-2")

        assert info1.path != info2.path
        assert info1.branch != info2.branch
        assert info1.path.is_dir()
        assert info2.path.is_dir()

        remove_worktree(git_repo, info1.path)
        remove_worktree(git_repo, info2.path)
