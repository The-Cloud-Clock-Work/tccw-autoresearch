"""Tests for agent profile generation."""

from __future__ import annotations

import json

from autoresearch.agent_profile import (
    DEFAULT_AGENT_DIR,
    ensure_agent_dir,
    generate_claude_md,
    generate_settings,
    init_autoresearch_dir,
    link_agent_defaults,
)
from autoresearch.marker import (
    AgentConfig,
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
    def test_uses_dont_ask_mode(self):
        marker = _make_marker()
        settings = generate_settings(marker)
        assert settings["defaultMode"] == "dontAsk"

    def test_mutable_allowed_for_edit(self):
        marker = _make_marker(target=Target(mutable=["tests/*.py", "src/lib.py"], immutable=[]))
        settings = generate_settings(marker)
        allow = settings["permissions"]["allow"]
        assert "Edit(tests/*.py)" in allow
        assert "Edit(src/lib.py)" in allow
        assert "Write(tests/*.py)" in allow

    def test_immutable_not_in_allow(self):
        """With dontAsk mode, immutable files are auto-denied by not being in allow."""
        marker = _make_marker(target=Target(mutable=["tests/*.py"], immutable=["src/engine.py"]))
        settings = generate_settings(marker)
        allow = settings["permissions"]["allow"]
        # Immutable files should NOT appear in allow
        assert "Edit(src/engine.py)" not in allow
        assert "Write(src/engine.py)" not in allow
        # And should NOT be in deny (dontAsk handles it, deny would override allow)
        deny = settings["permissions"]["deny"]
        assert "Edit(src/engine.py)" not in deny

    def test_read_always_allowed(self):
        marker = _make_marker()
        settings = generate_settings(marker)
        allow = settings["permissions"]["allow"]
        assert "Read" in allow  # bare Read matches all reads

    def test_grep_glob_always_allowed(self):
        marker = _make_marker()
        settings = generate_settings(marker)
        allow = settings["permissions"]["allow"]
        assert "Grep" in allow
        assert "Glob" in allow

    def test_agent_config_tools_normalized(self):
        """Legacy colon syntax is normalized to space syntax."""
        marker = _make_marker(agent=AgentConfig(
            allowed_tools=["Bash(pytest:*)"],
            disallowed_tools=["Bash(curl:*)"],
        ))
        settings = generate_settings(marker)
        assert "Bash(pytest *)" in settings["permissions"]["allow"]
        assert "Bash(curl *)" in settings["permissions"]["deny"]

    def test_comma_separated_tools_split(self):
        """Comma-separated tool specs are split into individual rules."""
        marker = _make_marker(agent=AgentConfig(
            allowed_tools=["Bash(python3:*,pytest:*)"],
            disallowed_tools=[],
        ))
        settings = generate_settings(marker)
        allow = settings["permissions"]["allow"]
        assert "Bash(python3 *)" in allow
        assert "Bash(pytest *)" in allow

    def test_redundant_wildcard_simplified(self):
        """Read(*) is simplified to bare Read."""
        marker = _make_marker(agent=AgentConfig(
            allowed_tools=["Read(*)"],
            disallowed_tools=[],
        ))
        settings = generate_settings(marker)
        allow = settings["permissions"]["allow"]
        assert "Read" in allow
        assert "Read(*)" not in allow

    def test_empty_immutable(self):
        marker = _make_marker(target=Target(mutable=["src/*.py"], immutable=[]))
        settings = generate_settings(marker)
        edit_denials = [d for d in settings["permissions"]["deny"] if d.startswith("Edit(")]
        assert edit_denials == []

    def test_disallowed_tool_appended_and_normalized(self):
        marker = _make_marker(agent=AgentConfig(
            allowed_tools=[],
            disallowed_tools=["Bash(docker:*)"],
        ))
        settings = generate_settings(marker)
        assert "Bash(docker *)" in settings["permissions"]["deny"]


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

    def test_custom_agent_gets_default_symlinks(self, tmp_path):
        marker = _make_marker(agent=AgentConfig(name="copilot"))
        paths = ensure_agent_dir(tmp_path, "test-marker", marker)
        # Should have symlinks from default agent
        rules_dir = paths.agent_dir / ".claude" / "rules"
        assert rules_dir.exists()
        for item in rules_dir.iterdir():
            if item.is_symlink():
                assert item.resolve().is_file()

    def test_default_agent_no_symlinks(self, tmp_path):
        marker = _make_marker(agent=AgentConfig(name="default"))
        paths = ensure_agent_dir(tmp_path, "test-marker", marker)
        # Default agent should NOT get symlinks
        symlinks = [f for f in paths.agent_dir.rglob("*") if f.is_symlink()]
        assert symlinks == []


class TestInitAutoresearchDir:
    def test_creates_autoresearch_directory(self, tmp_path):
        ar_dir = init_autoresearch_dir(tmp_path)
        assert ar_dir.is_dir()
        assert ar_dir == tmp_path / ".autoresearch"

    def test_copies_default_agent_files(self, tmp_path):
        ar_dir = init_autoresearch_dir(tmp_path)
        default_dst = ar_dir / "agents" / "default"
        assert default_dst.is_dir()
        # At least CLAUDE.md should be copied
        assert (default_dst / "CLAUDE.md").is_file()

    def test_additive_does_not_overwrite_existing(self, tmp_path):
        ar_dir = init_autoresearch_dir(tmp_path)
        claude_md = ar_dir / "agents" / "default" / "CLAUDE.md"
        claude_md.read_text()
        claude_md.write_text("custom override")
        # Run again — should NOT overwrite
        init_autoresearch_dir(tmp_path)
        assert claude_md.read_text() == "custom override"

    def test_symlinks_custom_agents(self, tmp_path):
        # Create a custom agent directory before calling init
        custom_agent = tmp_path / ".autoresearch" / "agents" / "custom"
        custom_agent.mkdir(parents=True, exist_ok=True)
        init_autoresearch_dir(tmp_path)
        # Custom agent should get symlinks from default
        symlinks = [f for f in custom_agent.rglob("*") if f.is_symlink()]
        assert len(symlinks) > 0

    def test_returns_autoresearch_path(self, tmp_path):
        result = init_autoresearch_dir(tmp_path)
        assert result == tmp_path / ".autoresearch"


class TestLinkAgentDefaults:
    def test_creates_symlinks(self, tmp_path):
        agent_dir = tmp_path / "custom"
        agent_dir.mkdir()
        link_agent_defaults(agent_dir, DEFAULT_AGENT_DIR)
        # Should have symlinks for default agent files
        symlinks = [f for f in agent_dir.rglob("*") if f.is_symlink()]
        assert len(symlinks) > 0

    def test_does_not_overwrite_real_files(self, tmp_path):
        agent_dir = tmp_path / "custom"
        agent_dir.mkdir()
        # Create a real file that conflicts
        claude_md = agent_dir / "CLAUDE.md"
        claude_md.write_text("custom content")
        link_agent_defaults(agent_dir, DEFAULT_AGENT_DIR)
        # Real file should be untouched
        assert claude_md.read_text() == "custom content"
        assert not claude_md.is_symlink()

    def test_does_not_overwrite_existing_symlinks(self, tmp_path):
        agent_dir = tmp_path / "custom"
        agent_dir.mkdir()
        # Create an existing symlink
        dummy = tmp_path / "dummy.md"
        dummy.write_text("dummy")
        claude_md = agent_dir / "CLAUDE.md"
        claude_md.symlink_to(dummy)
        link_agent_defaults(agent_dir, DEFAULT_AGENT_DIR)
        # Should still point to dummy
        assert claude_md.resolve() == dummy.resolve()

    def test_symlinks_resolve_to_default(self, tmp_path):
        agent_dir = tmp_path / "custom"
        agent_dir.mkdir()
        link_agent_defaults(agent_dir, DEFAULT_AGENT_DIR)
        # All symlinks should resolve to files under DEFAULT_AGENT_DIR
        for f in agent_dir.rglob("*"):
            if f.is_symlink():
                resolved = f.resolve()
                assert str(resolved).startswith(str(DEFAULT_AGENT_DIR.resolve()))
