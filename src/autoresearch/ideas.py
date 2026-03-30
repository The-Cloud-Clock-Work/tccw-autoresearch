"""Ideas backlog management (.autoresearch/<marker>/ideas.md)."""

from __future__ import annotations

from pathlib import Path

from autoresearch.results import RESULTS_DIR, ensure_results_dir


IDEAS_FILE = "ideas.md"

SECTIONS = {
    "Discarded but Promising": "## Discarded but Promising",
    "Near-Misses": "## Near-Misses",
    "External Research": "## External Research (from SEARCH escalation)",
}

TEMPLATE = """# Ideas Backlog -- {marker_name}

## Discarded but Promising

## Near-Misses

## External Research (from SEARCH escalation)
"""


def _ideas_path(repo_path: Path, marker_name: str) -> Path:
    return repo_path / RESULTS_DIR / marker_name / IDEAS_FILE


def create_ideas_template(repo_path: Path, marker_name: str) -> None:
    """Create ideas.md with section headers if it doesn't exist."""
    path = _ideas_path(repo_path, marker_name)
    if path.is_file():
        return
    ensure_results_dir(repo_path, marker_name)
    path.write_text(TEMPLATE.format(marker_name=marker_name))


def read_ideas(repo_path: Path, marker_name: str) -> str:
    """Read ideas.md content. Return empty string if missing."""
    path = _ideas_path(repo_path, marker_name)
    if not path.is_file():
        return ""
    return path.read_text()


def append_idea(repo_path: Path, marker_name: str, section: str, entry: str) -> None:
    """Append entry to a section in ideas.md.

    section: One of 'Discarded but Promising', 'Near-Misses', 'External Research'
    entry: Markdown text to append (will be prefixed with '- ')
    Creates file with template if missing.
    """
    if section not in SECTIONS:
        raise ValueError(f"Unknown section: {section}. Valid: {list(SECTIONS.keys())}")

    create_ideas_template(repo_path, marker_name)
    path = _ideas_path(repo_path, marker_name)
    content = path.read_text()

    section_header = SECTIONS[section]
    formatted_entry = f"- {entry}"

    lines = content.split("\n")
    result = []
    in_target_section = False
    inserted = False

    for i, line in enumerate(lines):
        # Check if we hit the NEXT section header (any ## line) after our target
        if in_target_section and not inserted and line.startswith("## "):
            # Insert before the next section
            result.append(formatted_entry)
            result.append("")
            inserted = True
            in_target_section = False

        result.append(line)

        if line.strip() == section_header:
            in_target_section = True

    # If target was the last section, append at end
    if in_target_section and not inserted:
        result.append(formatted_entry)
        inserted = True

    path.write_text("\n".join(result))
