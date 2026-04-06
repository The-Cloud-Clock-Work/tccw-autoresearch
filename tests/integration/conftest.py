"""Shared fixtures for integration tests."""

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def git_repo(tmp_path):
    """Create a bare git repo with an initial commit."""
    repo = tmp_path / "test-repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, capture_output=True, check=True)
    (repo / "README.md").write_text("# test\n")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True, check=True)
    return repo


@pytest.fixture
def git_repo_with_ruff_errors(git_repo):
    """Git repo seeded with files that have known ruff errors."""
    src = FIXTURES_DIR / "ruff_errors.py"
    shutil.copy(src, git_repo / "main.py")
    subprocess.run(["git", "add", "."], cwd=git_repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "add ruff errors"], cwd=git_repo, capture_output=True, check=True)
    return git_repo


@pytest.fixture
def marker_config():
    """Factory for creating .autoresearch/config.yaml content."""
    def _make(
        name="test-marker",
        command="ruff check . 2>&1",
        extract=r"grep -oP 'Found \K\d+'",
        direction="lower",
        baseline=5,
        mutable=None,
        budget="5m",
        **overrides,
    ):
        config = {
            "markers": [{
                "name": name,
                "description": "Integration test marker",
                "status": "active",
                "target": {
                    "mutable": mutable or ["*.py"],
                },
                "metric": {
                    "command": command,
                    "extract": extract,
                    "direction": direction,
                    "baseline": baseline,
                },
                "agent": {
                    "model": "sonnet",
                    "budget_per_experiment": budget,
                    "max_experiments": 1,
                },
            }],
        }
        config["markers"][0].update(overrides)
        return config
    return _make


@pytest.fixture
def write_marker_config(marker_config):
    """Write a marker config to a repo's .autoresearch/config.yaml."""
    def _write(repo_path, **kwargs):
        ar_dir = repo_path / ".autoresearch"
        ar_dir.mkdir(exist_ok=True)
        config_path = ar_dir / "config.yaml"
        config_path.write_text(yaml.dump(marker_config(**kwargs)))
        return config_path
    return _write
