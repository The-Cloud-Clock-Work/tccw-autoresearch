"""Agent profile generation: settings.json + CLAUDE.md per marker."""

from __future__ import annotations

import json
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


def _load_default_settings() -> dict:
    """Load the default agent settings.json as base."""
    default_path = DEFAULT_AGENT_DIR / "settings.json"
    if default_path.is_file():
        return json.loads(default_path.read_text())
    return {"permissions": {"allow": [], "deny": []}}


def generate_settings(marker: Marker) -> dict:
    """Generate settings.json content from marker config.

    Starts from default agent settings, then adds:
    - Allow edits only to mutable files
    - Deny edits to immutable files
    - Merge marker.agent.allowed_tools / disallowed_tools
    """
    base = _load_default_settings()
    allow = list(base.get("permissions", {}).get("allow", []))
    deny = list(base.get("permissions", {}).get("deny", []))

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


def generate_claude_md(marker: Marker) -> str:
    """Generate CLAUDE.md system prompt content from marker config.

    Starts from default agent CLAUDE.md, appends marker-specific context.
    """
    # Load default agent instructions
    default_md_path = DEFAULT_AGENT_DIR / "CLAUDE.md"
    base = default_md_path.read_text() if default_md_path.is_file() else ""

    lines = [base.rstrip(), ""]
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


def ensure_agent_dir(
    worktree_path: Path,
    marker_name: str,
    marker: Marker,
) -> AgentPaths:
    """Create .autoresearch/agents/<marker>/ with settings.json and CLAUDE.md.

    Returns AgentPaths with all relevant paths.
    """
    agent_dir = worktree_path / ".autoresearch" / "agents" / marker_name
    logs_dir = agent_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    settings = generate_settings(marker)
    settings_path = agent_dir / "settings.json"
    settings_path.write_text(json.dumps(settings, indent=2))

    claude_md = generate_claude_md(marker)
    claude_md_path = agent_dir / "CLAUDE.md"
    claude_md_path.write_text(claude_md)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    return AgentPaths(
        agent_dir=agent_dir,
        settings_path=settings_path,
        claude_md_path=claude_md_path,
        logs_dir=logs_dir,
        stream_log_path=logs_dir / f"run-{ts}.jsonl",
        debug_log_path=logs_dir / f"debug-{ts}.log",
    )
