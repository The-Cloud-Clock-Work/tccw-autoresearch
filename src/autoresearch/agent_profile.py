"""Agent profile generation: settings.json + CLAUDE.md per marker."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from autoresearch.marker import Marker

DEFAULT_AGENT_DIR = Path(__file__).parent / "agents" / "default"


@dataclass
class AgentPaths:
    agent_dir: Path
    settings_path: Path
    claude_md_path: Path
    logs_dir: Path
    stream_log_path: Path
    debug_log_path: Path
    env: dict = field(default_factory=dict)


def resolve_agent_dir(repo_path: Path, agent_name: str) -> Path | None:
    """Resolve agent name to its directory in the repo's .autoresearch/agents/.

    Returns None if the agent doesn't exist in the repo.
    """
    repo_agent_dir = repo_path / ".autoresearch" / "agents" / agent_name
    if repo_agent_dir.is_dir():
        return repo_agent_dir
    return None


def _load_agent_base(repo_path: Path, agent_name: str) -> tuple[dict, str, dict]:
    """Load settings.json and CLAUDE.md from the named agent profile.

    Resolution order:
    1. .autoresearch/agents/<name>/ in the repo
    2. src/autoresearch/agents/default/ (shipped default)

    Returns (settings_dict, claude_md_string, env_dict).
    """
    repo_dir = resolve_agent_dir(repo_path, agent_name)
    if repo_dir:
        base_dir = repo_dir
    else:
        base_dir = DEFAULT_AGENT_DIR

    settings_path = base_dir / "settings.json"
    settings = json.loads(settings_path.read_text()) if settings_path.is_file() else {"permissions": {"allow": [], "deny": []}}

    claude_md_path = base_dir / "CLAUDE.md"
    claude_md = claude_md_path.read_text() if claude_md_path.is_file() else ""

    agent_env = settings.get("env", {})

    return settings, claude_md, agent_env


def generate_settings(marker: Marker, repo_path: Path | None = None) -> dict:
    """Generate settings.json from marker config.

    Uses dontAsk mode: auto-denies everything not in permissions.allow.
    This means:
      - Mutable files → Edit/Write in allow (agent CAN edit these)
      - Immutable files → NOT in allow (dontAsk auto-denies them)
      - Read always allowed (agent needs full context)
      - deny list only for explicit extra blocks (disallowed_tools)

    deny > allow in Claude Code's precedence, so we NEVER put catch-all
    Edit/Write in deny — that would block even the allowed mutable files.
    """
    base_settings, _, _ = _load_agent_base(repo_path or Path("."), marker.agent.name)
    allow = list(base_settings.get("permissions", {}).get("allow", []))
    deny = list(base_settings.get("permissions", {}).get("deny", []))

    # Mutable files: agent CAN edit these
    for pattern in marker.target.mutable:
        rule_edit = f"Edit({pattern})"
        rule_write = f"Write({pattern})"
        if rule_edit not in allow:
            allow.append(rule_edit)
        if rule_write not in allow:
            allow.append(rule_write)

    # Immutable files: NOT added to allow → dontAsk auto-denies them
    # No need to add to deny (dontAsk handles it, and deny would
    # override allow if someone later adds the file to both lists)

    # Agent always needs to read everything for context
    if "Read" not in allow:
        allow.append("Read")

    # Glob/Grep for codebase exploration
    if "Grep" not in allow:
        allow.append("Grep")
    if "Glob" not in allow:
        allow.append("Glob")

    # Merge allowed_tools from marker agent config (normalize syntax)
    for tool in marker.agent.allowed_tools:
        for normalized in _normalize_tool_rules(tool):
            if normalized not in allow:
                allow.append(normalized)

    # Merge disallowed_tools into deny (normalize syntax)
    for tool in marker.agent.disallowed_tools:
        for normalized in _normalize_tool_rules(tool):
            if normalized not in deny:
                deny.append(normalized)

    return {
        "defaultMode": "dontAsk",
        "permissions": {
            "allow": allow,
            "deny": deny,
        },
    }


def _normalize_tool_rules(rule: str) -> list[str]:
    """Normalize a tool permission rule to Claude Code's current syntax.

    Handles:
    - Comma-separated rules: "Bash(python3:*,pytest:*)" → ["Bash(python3 *)", "Bash(pytest *)"]
    - Legacy colon syntax: "Bash(rm:*)" → "Bash(rm *)"
    - Redundant rules: "Read(*)" → "Read" (bare tool matches all)
    - Pass-through for already-correct rules
    """
    # Check for Tool(specifier) format
    if "(" not in rule or not rule.endswith(")"):
        return [rule]

    paren_start = rule.index("(")
    tool_name = rule[:paren_start]
    specifier = rule[paren_start + 1 : -1]

    # Bare wildcard is redundant: Read(*) == Read
    if specifier == "*":
        return [tool_name]

    # Split comma-separated specifiers into individual rules
    parts = [s.strip() for s in specifier.split(",")]

    results = []
    for part in parts:
        # Normalize legacy colon syntax: "rm:*" → "rm *"
        if ":*" in part:
            part = part.replace(":*", " *")
        elif ":" in part and not part.startswith("domain:"):
            # "rm:-rf" → "rm -rf" (colon as separator, not domain prefix)
            part = part.replace(":", " ", 1)
        results.append(f"{tool_name}({part})")

    return results


def build_cli_permission_flags(marker: Marker, repo_path: Path | None = None) -> tuple[list[str], list[str]]:
    """Build --allowedTools and --disallowedTools CLI flag values from marker config.

    CLI flags are the reliable enforcement mechanism — settings.json dontAsk mode
    doesn't block Edit tools that aren't in allow. CLI flags do.

    Returns (allowed_tools, disallowed_tools) as flat lists of rule strings.
    """
    settings = generate_settings(marker, repo_path)
    allowed = settings["permissions"]["allow"]

    # Build deny list: start with explicit disallowed_tools
    denied = list(settings["permissions"]["deny"])

    # Add catch-all deny for Edit/Write on everything NOT mutable
    # This is safe as CLI flag because --disallowedTools is checked AFTER --allowedTools
    # when both match (unlike settings.json where deny always wins)
    #
    # Actually, per the docs deny > allow in ALL contexts. So we can't use catch-all
    # deny with specific allows. Instead, deny the immutable paths explicitly.
    for pattern in marker.target.immutable:
        denied.append(f"Edit({pattern})")
        denied.append(f"Write({pattern})")

    # Deny Edit/Write on src/** as a safety net (common immutable root)
    # Only if no mutable files are under src/
    mutable_in_src = any(p.startswith("src/") for p in marker.target.mutable)
    if not mutable_in_src:
        denied.append("Edit(src/**)")
        denied.append("Write(src/**)")

    return allowed, denied


def generate_claude_md(marker: Marker, repo_path: Path | None = None) -> str:
    """Generate CLAUDE.md from agent base + marker-specific context."""
    _, base_md, _ = _load_agent_base(repo_path or Path("."), marker.agent.name)

    lines = [base_md.rstrip(), ""]
    lines.append(f"# Marker: {marker.name}")
    if marker.description:
        lines.append(f"Description: {marker.description}")
    lines.append("")
    lines.append("## File Permissions")
    lines.append("### Mutable (you CAN edit these):")
    for f in marker.target.mutable:
        lines.append(f"- {f}")
    lines.append("")
    lines.append("### Immutable (you MUST NOT edit these):")
    if marker.target.immutable:
        for f in marker.target.immutable:
            lines.append(f"- {f}")
    else:
        lines.append("- Any file outside the mutable set")
    lines.append("")
    return "\n".join(lines)


def init_autoresearch_dir(repo_path: Path) -> Path:
    """Create .autoresearch/ directory with default agent profile.

    Additive only — never overwrites existing files.
    Returns the .autoresearch/ path.
    """
    ar_dir = repo_path / ".autoresearch"

    # Walk the shipped default agent and copy everything that doesn't exist yet
    for src_file in DEFAULT_AGENT_DIR.rglob("*"):
        if not src_file.is_file():
            continue
        rel = src_file.relative_to(DEFAULT_AGENT_DIR)
        dst = ar_dir / "agents" / "default" / rel
        if not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dst)

    # Symlink default agent files into all custom agents
    agents_dir = ar_dir / "agents"
    if agents_dir.is_dir():
        default_src = agents_dir / "default"
        for agent_dir in agents_dir.iterdir():
            if agent_dir.is_dir() and agent_dir.name != "default":
                link_agent_defaults(agent_dir, default_src)

    return ar_dir


def link_agent_defaults(agent_dir: Path, default_dir: Path) -> None:
    """Symlink default agent files into a custom agent dir.

    Non-destructive: only creates symlinks where no file or symlink exists.
    Existing real files and symlinks are never touched.
    """
    for src in default_dir.rglob("*"):
        if not src.is_file():
            continue
        rel = src.relative_to(default_dir)
        dst = agent_dir / rel
        if dst.exists() or dst.is_symlink():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        # Relative symlink: portable across machines
        relative_target = os.path.relpath(src.resolve(), dst.parent.resolve())
        dst.symlink_to(relative_target)


def ensure_agent_dir(
    worktree_path: Path,
    marker_name: str,
    marker: Marker,
) -> AgentPaths:
    """Create runtime agent dir with generated settings.json and CLAUDE.md.

    Uses the repo's .autoresearch/agents/<name>/ as base if it exists,
    otherwise falls back to the shipped default.
    """
    agent_dir = worktree_path / ".autoresearch" / "agents" / marker_name
    logs_dir = agent_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    settings = generate_settings(marker, worktree_path)
    settings_path = agent_dir / "settings.json"
    settings_path.write_text(json.dumps(settings, indent=2))

    claude_md = generate_claude_md(marker, worktree_path)
    claude_md_path = agent_dir / "CLAUDE.md"
    claude_md_path.write_text(claude_md)

    # Symlink default agent files into custom agent dirs
    if marker.agent.name != "default":
        link_agent_defaults(agent_dir, DEFAULT_AGENT_DIR)

    # Load env vars from agent profile settings.json (OTEL, etc.)
    _, _, agent_env = _load_agent_base(worktree_path, marker.agent.name)

    # Write settings.local.json so Claude Code reads the env block (OTEL,
    # telemetry) and hooks (budget countdown). Claude walks UP from CWD
    # looking for .claude/ — the agent runs from .autoresearch/agents/<name>/
    # which has its own .claude/ dir. Write THERE (agent CWD) AND at worktree root.
    local_settings: dict = {}
    if agent_env:
        local_settings["env"] = agent_env

    # Budget countdown hook — PostToolUse injects remaining time as additionalContext
    hook_script = agent_dir / "hooks" / "budget-countdown.sh"
    if hook_script.is_file() or (agent_dir / "hooks").is_dir():
        # Resolve through symlinks to get the real path
        resolved = hook_script.resolve() if hook_script.exists() else None
        if resolved and resolved.is_file():
            local_settings["hooks"] = {
                "PostToolUse": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": f"bash {resolved}",
                                "timeout": 3,
                            }
                        ]
                    }
                ]
            }

    if local_settings:
        for claude_dir in [
            agent_dir / ".claude",                  # agent CWD (found first)
            worktree_path / ".claude",              # worktree root (fallback)
        ]:
            local_settings_path = claude_dir / "settings.local.json"
            claude_dir.mkdir(parents=True, exist_ok=True)
            existing = {}
            if local_settings_path.is_file():
                existing = json.loads(local_settings_path.read_text())
            existing.update(local_settings)
            local_settings_path.write_text(json.dumps(existing, indent=2))

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    return AgentPaths(
        agent_dir=agent_dir,
        settings_path=settings_path,
        claude_md_path=claude_md_path,
        logs_dir=logs_dir,
        stream_log_path=logs_dir / f"run-{ts}.jsonl",
        debug_log_path=logs_dir / f"debug-{ts}.log",
        env=agent_env,
    )
