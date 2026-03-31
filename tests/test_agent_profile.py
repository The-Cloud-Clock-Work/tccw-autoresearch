"""Tests for agent profile generation."""

from __future__ import annotations

import json
from pathlib import Path

from autoresearch.agent_profile import (
    AgentPaths,
    ensure_agent_dir,
    generate_claude_md,
    generate_settings,
)
from autoresearch.marker import (
    AgentConfig,
    Guard,
    LoopConfig,
    Marker,
    Metric,
    Target,
)


def _make_marker(**overrides) -> Marker:
    defaults = {
        "name": "test-marker",
        "description": "Test marker",
        "target": Target(mutable=["tests/test_main.py"], immutable=["src/main.py"]),
        "metric": Metric(command="echo 1", extract=r"\d+", direction="higher", baseline=1.0),
        "loop": LoopConfig(model="sonnet", budget_per_experiment="10m", max_experiments=10),
    }
    defaults.update(overrides)
    return Marker(**defaults)


class TestGenerateSettings:
    def test_mutable_allowed_for_edit(self):
        marker = _make_marker(target=Target(mutable=["tests/*.py", "src/lib.py"], immutable=[]))
        settings = generate_settings(marker)
        allow = settings["permissions"]["allow"]
        assert "Edit(tests/*.py)" in allow
        assert "Edit(src/lib.py)" in allow

    def test_immutable_denied_for_edit(self):
        marker = _make_marker(target=Target(mutable=["tests/*.py"], immutable=["src/engine.py"]))
        settings = generate_settings(marker)
        deny = settings["permissions"]["deny"]
        assert "Edit(src/engine.py)" in deny
        assert "Write(src/engine.py)" in deny

    def test_destructive_ops_denied(self):
        marker = _make_marker()
        settings = generate_settings(marker)
        deny = settings["permissions"]["deny"]
        assert "Bash(rm -rf:*)" in deny
        assert "Bash(git push:*)" in deny

    def test_reads_always_allowed(self):
        marker = _make_marker()
        settings = generate_settings(marker)
        allow = settings["permissions"]["allow"]
        assert "Read(*)" in allow

    def test_agent_config_tools_merged(self):
        marker = _make_marker(agent=AgentConfig(
            allowed_tools=["Bash(pytest:*)"],
            disallowed_tools=["Bash(curl:*)"],
        ))
        settings = generate_settings(marker)
        assert "Bash(pytest:*)" in settings["permissions"]["allow"]
        assert "Bash(curl:*)" in settings["permissions"]["deny"]

    def test_empty_immutable(self):
        marker = _make_marker(target=Target(mutable=["src/*.py"], immutable=[]))
        settings = generate_settings(marker)
        # No Edit denials (only destructive bash)
        edit_denials = [d for d in settings["permissions"]["deny"] if d.startswith("Edit(")]
        assert edit_denials == []


class TestGenerateClaudeMd:
    def test_contains_marker_name(self):
        marker = _make_marker()
        md = generate_claude_md(marker)
        assert "test-marker" in md

    def test_contains_mutable_files(self):
        marker = _make_marker(target=Target(mutable=["tests/test_main.py"], immutable=[]))
        md = generate_claude_md(marker)
        assert "tests/test_main.py" in md

    def test_contains_immutable_files(self):
        marker = _make_marker(target=Target(mutable=["x.py"], immutable=["src/engine.py"]))
        md = generate_claude_md(marker)
        assert "src/engine.py" in md

    def test_contains_rules(self):
        marker = _make_marker()
        md = generate_claude_md(marker)
        assert "NEVER ask for human input" in md
        assert "NEVER edit immutable files" in md

    def test_contains_description(self):
        marker = _make_marker(description="Improve test coverage")
        md = generate_claude_md(marker)
        assert "Improve test coverage" in md


class TestEnsureAgentDir:
    def test_creates_directory_structure(self, tmp_path):
        marker = _make_marker()
        paths = ensure_agent_dir(tmp_path, "test-marker", marker)
        assert paths.agent_dir.is_dir()
        assert paths.logs_dir.is_dir()
        assert paths.settings_path.is_file()
        assert paths.claude_md_path.is_file()

    def test_settings_is_valid_json(self, tmp_path):
        marker = _make_marker()
        paths = ensure_agent_dir(tmp_path, "test-marker", marker)
        data = json.loads(paths.settings_path.read_text())
        assert "permissions" in data

    def test_claude_md_contains_marker(self, tmp_path):
        marker = _make_marker()
        paths = ensure_agent_dir(tmp_path, "test-marker", marker)
        content = paths.claude_md_path.read_text()
        assert "test-marker" in content

    def test_log_paths_have_timestamp(self, tmp_path):
        marker = _make_marker()
        paths = ensure_agent_dir(tmp_path, "test-marker", marker)
        assert "run-" in paths.stream_log_path.name
        assert "debug-" in paths.debug_log_path.name

    def test_idempotent(self, tmp_path):
        marker = _make_marker()
        paths1 = ensure_agent_dir(tmp_path, "test-marker", marker)
        paths2 = ensure_agent_dir(tmp_path, "test-marker", marker)
        assert paths1.agent_dir == paths2.agent_dir
