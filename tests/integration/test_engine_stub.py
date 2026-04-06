"""Integration Test 5: Full engine loop with stub Claude binary.

Requires claude-stub.sh on PATH (or uses monkeypatch to inject it).
Tests the complete run_marker pipeline with a fake Claude that makes
a real file change and outputs valid stream-json.
"""

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

from autoresearch.engine import ClaudeCodeRunner, get_agent_runner, run_marker
from autoresearch.marker import load_markers
from autoresearch.state import AppState, TrackedMarker

FIXTURES_DIR = Path(__file__).parent / "fixtures"
STUB_PATH = FIXTURES_DIR / "claude-stub.sh"


@pytest.fixture
def claude_on_path(tmp_path, monkeypatch):
    """Put claude-stub.sh on PATH as 'claude'."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub_dest = bin_dir / "claude"
    shutil.copy(STUB_PATH, stub_dest)
    stub_dest.chmod(stub_dest.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    return stub_dest


@pytest.fixture
def engine_repo(git_repo):
    """Git repo with ruff errors + marker config ready for engine."""
    # Copy ruff errors fixture
    shutil.copy(FIXTURES_DIR / "ruff_errors.py", git_repo / "main.py")
    subprocess.run(["git", "add", "."], cwd=git_repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "add ruff errors"],
        cwd=git_repo, capture_output=True, check=True,
    )

    # Write marker config
    ar_dir = git_repo / ".autoresearch"
    ar_dir.mkdir()
    config = {
        "markers": [{
            "name": "ruff-fix",
            "description": "Fix ruff errors",
            "status": "active",
            "target": {"mutable": ["*.py"]},
            "metric": {
                "command": "ruff check . 2>&1",
                "extract": "grep -oP 'Found \\K\\d+'",
                "direction": "lower",
                "baseline": 10,
            },
            "agent": {
                "model": "stub",
                "budget_per_experiment": "5m",
                "max_experiments": 1,
            },
        }],
    }
    (ar_dir / "config.yaml").write_text(yaml.dump(config))

    # Create default agent dir
    agent_dir = ar_dir / "agents" / "default"
    agent_dir.mkdir(parents=True)
    (agent_dir / "CLAUDE.md").write_text("# Test Agent\nFix ruff errors.")
    (agent_dir / "settings.json").write_text(json.dumps({
        "permissions": {"allow": ["Read", "Edit", "Write"], "deny": []},
    }))

    subprocess.run(["git", "add", "."], cwd=git_repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "add autoresearch config"],
        cwd=git_repo, capture_output=True, check=True,
    )
    return git_repo


@pytest.mark.skipif(
    not STUB_PATH.exists(),
    reason="claude-stub.sh fixture not found",
)
class TestEngineStub:
    def test_run_marker_with_stub(self, engine_repo, claude_on_path, tmp_path):
        """Full engine loop: stub claude fixes a file, metric improves."""
        marker_file = load_markers(engine_repo / ".autoresearch" / "config.yaml")
        marker = marker_file.markers[0]

        state = AppState()
        tracked = TrackedMarker(
            id=f"{engine_repo.name}:{marker.name}",
            repo_path=str(engine_repo),
            repo_name=engine_repo.name,
            marker_name=marker.name,
        )
        state.markers.append(tracked)

        state_path = tmp_path / "state.json"
        runner = get_agent_runner(marker)

        result = run_marker(
            repo_path=engine_repo,
            marker=marker,
            state=state,
            tracked=tracked,
            agent_runner=runner,
            state_path=state_path,
            worktree_base=tmp_path / "worktrees",
            cleanup_worktree=True,
        )

        # Engine completed
        assert result.final_status in ("completed", "budget_exhausted")
        assert result.experiments >= 1

    def test_stub_claude_produces_valid_output(self, engine_repo, claude_on_path):
        """Verify the stub outputs parseable stream-json."""
        result = subprocess.run(
            ["claude", "-p", "test", "--add-dir", str(engine_repo)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        lines = result.stdout.strip().splitlines()
        for line in lines:
            parsed = json.loads(line)
            assert "type" in parsed

    def test_stub_modifies_file(self, engine_repo, claude_on_path):
        """Verify the stub actually changes main.py."""
        original = (engine_repo / "main.py").read_text()
        subprocess.run(
            ["claude", "-p", "test", "--add-dir", str(engine_repo)],
            capture_output=True, text=True,
        )
        modified = (engine_repo / "main.py").read_text()
        assert original != modified
        assert "x = 1" in modified
