"""Integration Test 1: autoresearch init --no-claude scaffolding."""

import yaml
from typer.testing import CliRunner

from autoresearch.cli import app

runner = CliRunner()


class TestInitScaffolding:
    def test_init_creates_autoresearch_dir(self, git_repo):
        result = runner.invoke(app, ["init", "--path", str(git_repo), "--no-claude"])
        assert result.exit_code == 0
        assert (git_repo / ".autoresearch").is_dir()

    def test_init_creates_config_yaml(self, git_repo):
        runner.invoke(app, ["init", "--path", str(git_repo), "--no-claude"])
        config_path = git_repo / ".autoresearch" / "config.yaml"
        assert config_path.is_file()
        data = yaml.safe_load(config_path.read_text())
        assert "markers" in data

    def test_init_creates_default_agent(self, git_repo):
        runner.invoke(app, ["init", "--path", str(git_repo), "--no-claude"])
        agent_dir = git_repo / ".autoresearch" / "agents" / "default"
        assert agent_dir.is_dir()
        assert (agent_dir / "CLAUDE.md").is_file()
        assert (agent_dir / "settings.json").is_file()

    def test_init_idempotent(self, git_repo):
        runner.invoke(app, ["init", "--path", str(git_repo), "--no-claude"])
        result = runner.invoke(app, ["init", "--path", str(git_repo), "--no-claude"])
        assert result.exit_code == 0

    def test_init_non_git_repo_fails_gracefully(self, tmp_path):
        non_repo = tmp_path / "not-a-repo"
        non_repo.mkdir()
        result = runner.invoke(app, ["init", "--path", str(non_repo), "--no-claude"])
        # Should either fail or warn — not crash
        assert result.exit_code in (0, 1)
