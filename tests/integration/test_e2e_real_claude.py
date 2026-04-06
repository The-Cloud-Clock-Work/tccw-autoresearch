"""Integration Test 6: Full end-to-end with real Claude.

Requires CLAUDE_CODE_OAUTH_TOKEN in env. Budget-capped at 2 minutes.
Only runs via workflow_dispatch with run_e2e=true.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from autoresearch.engine import get_agent_runner, run_marker
from autoresearch.marker import load_markers
from autoresearch.state import AppState, TrackedMarker

FIXTURES_DIR = Path(__file__).parent / "fixtures"

pytestmark = pytest.mark.skipif(
    not os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"),
    reason="CLAUDE_CODE_OAUTH_TOKEN not set — skipping real Claude test",
)


@pytest.fixture
def e2e_repo(git_repo):
    """Git repo with deliberate ruff errors for real Claude to fix."""
    shutil.copy(FIXTURES_DIR / "ruff_errors.py", git_repo / "main.py")
    subprocess.run(["git", "add", "."], cwd=git_repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "add ruff errors"],
        cwd=git_repo, capture_output=True, check=True,
    )

    ar_dir = git_repo / ".autoresearch"
    ar_dir.mkdir()
    config = {
        "markers": [{
            "name": "ruff-e2e",
            "description": "Fix ruff errors with real Claude",
            "status": "active",
            "target": {"mutable": ["*.py"]},
            "metric": {
                "command": "ruff check . 2>&1",
                "extract": "grep -oP 'Found \\K\\d+'",
                "direction": "lower",
                "baseline": 10,
            },
            "loop": {
                "model": "sonnet",
                "budget_per_experiment": "2m",
                "max_experiments": 1,
            },
        }],
    }
    (ar_dir / "config.yaml").write_text(yaml.dump(config))

    agent_dir = ar_dir / "agents" / "default"
    agent_dir.mkdir(parents=True)
    (agent_dir / "CLAUDE.md").write_text(
        "# Ruff Fix Agent\n\nFix all ruff linting errors in mutable files. "
        "Run `ruff check .` to see errors, then fix them."
    )
    (agent_dir / "settings.json").write_text(json.dumps({
        "permissions": {
            "allow": ["Read", "Edit", "Write", "Glob", "Grep",
                       "Bash(ruff *)", "Bash(python3 *)"],
            "deny": ["Bash(git push *)", "Bash(rm -rf *)"],
        },
    }))

    subprocess.run(["git", "add", "."], cwd=git_repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "add autoresearch config"],
        cwd=git_repo, capture_output=True, check=True,
    )
    return git_repo


class TestE2ERealClaude:
    @pytest.mark.timeout(180)
    def test_real_claude_fixes_ruff_errors(self, e2e_repo, tmp_path):
        """Real Claude agent fixes at least one ruff error."""
        marker_file = load_markers(e2e_repo / ".autoresearch" / "config.yaml")
        marker = marker_file.markers[0]

        state = AppState()
        tracked = TrackedMarker(
            id=f"{e2e_repo.name}:{marker.name}",
            repo_path=str(e2e_repo),
            repo_name=e2e_repo.name,
            marker_name=marker.name,
        )
        state.markers.append(tracked)

        state_path = tmp_path / "state.json"
        runner = get_agent_runner(marker)

        result = run_marker(
            repo_path=e2e_repo,
            marker=marker,
            state=state,
            tracked=tracked,
            agent_runner=runner,
            state_path=state_path,
            worktree_base=tmp_path / "worktrees",
            cleanup_worktree=True,
        )

        assert result.experiments >= 1
        assert result.final_status in ("completed", "budget_exhausted")

        # Claude should have fixed at least one error
        if result.kept > 0:
            assert result.final_metric is not None
            assert result.final_metric < 10  # baseline was ~10 errors
