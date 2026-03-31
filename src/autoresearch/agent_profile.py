"""Agent profile generation: settings.json + CLAUDE.md per marker."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
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


def resolve_agent_dir(repo_path: Path, agent_name: str) -> Path | None:
    """Resolve agent name to its directory in the repo's .autoresearch/agents/.

    Returns None if the agent doesn't exist in the repo.
    """
    repo_agent_dir = repo_path / ".autoresearch" / "agents" / agent_name
    if repo_agent_dir.is_dir():
        return repo_agent_dir
    return None


def _load_agent_base(repo_path: Path, agent_name: str) -> tuple[dict, str]:
    """Load settings.json and CLAUDE.md from the named agent profile.

    Resolution order:
    1. .autoresearch/agents/<name>/ in the repo
    2. src/autoresearch/agents/default/ (shipped default)
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

    return settings, claude_md


def generate_settings(marker: Marker, repo_path: Path | None = None) -> dict:
    """Generate settings.json content from agent base + marker overrides."""
    base_settings, _ = _load_agent_base(repo_path or Path("."), marker.agent.name)
    allow = list(base_settings.get("permissions", {}).get("allow", []))
    deny = list(base_settings.get("permissions", {}).get("deny", []))

    for pattern in marker.target.mutable:
        allow.append(f"Edit({pattern})")
        allow.append(f"Write({pattern})")

    for pattern in marker.target.immutable:
        deny.append(f"Edit({pattern})")
        deny.append(f"Write({pattern})")

    for tool in marker.agent.allowed_tools:
        if tool not in allow:
            allow.append(tool)

    for tool in marker.agent.disallowed_tools:
        if tool not in deny:
            deny.append(tool)

    return {"permissions": {"allow": allow, "deny": deny}}


def generate_claude_md(marker: Marker, repo_path: Path | None = None) -> str:
    """Generate CLAUDE.md from agent base + marker-specific context."""
    _, base_md = _load_agent_base(repo_path or Path("."), marker.agent.name)

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
        dst.symlink_to(src)


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

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    return AgentPaths(
        agent_dir=agent_dir,
        settings_path=settings_path,
        claude_md_path=claude_md_path,
        logs_dir=logs_dir,
        stream_log_path=logs_dir / f"run-{ts}.jsonl",
        debug_log_path=logs_dir / f"debug-{ts}.log",
    )
