"""Program.md template generation from marker config."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from string import Template

from autoresearch.marker import Marker

logger = logging.getLogger(__name__)


PROGRAM_TEMPLATE = Template("""\
## Identity
You are an autonomous self-improvement agent.

## Scope
You may edit files in:
$mutable

You may NOT edit:
$immutable
- Any file outside the listed mutable set

## Metric
Run: `$metric_command`
Extract: `$metric_extract`
Objective: $direction is better
$baseline_line
$target_line

## Simplicity Criterion
A marginal improvement that adds complexity? Probably discard.
An equal result with less code? Definitely keep.

## Your Task (ONE experiment)
$issues_section
1. Read the specific files listed in the issues above
2. Fix as many issues as you can — focus on the highest severity first
3. git commit with a descriptive message
4. EXIT — you are done. The engine will run the metric harness and decide keep/discard.

IMPORTANT: Do NOT run the metric harness yourself. Do NOT loop. Do NOT explore broadly.
Fix the SPECIFIC issues listed above, commit, and exit. Be surgical.

## Time Budget
You have $budget to make your changes. Go straight to the files, fix the issues, commit.

$escalation_section\
$results_section\
$ideas_section\
""")


def generate_program(
    marker: Marker,
    current_best: float | None,
    results_summary: str,
    ideas_content: str,
    escalation_level: str = "normal",
    repo_path: Path | None = None,
) -> str:
    """Generate the program.md instruction document from a marker.

    Args:
        marker: The marker configuration.
        current_best: Current best metric value (None if no experiments yet).
        results_summary: Formatted results history (truncated).
        ideas_content: Content from ideas.md.
        escalation_level: Current escalation level (normal/refine/pivot/search/halt).
        repo_path: Repository path for running issues_command.

    Returns:
        Complete program.md content as a string.
    """
    if current_best is not None:
        baseline_line = f"Baseline: {marker.metric.baseline}    Current best: {current_best}"
    else:
        baseline_line = f"Baseline: {marker.metric.baseline} (no experiments yet)"

    target_line = f"Target: {marker.metric.target}" if marker.metric.target else ""

    issues_section = _fetch_issues(marker, repo_path)

    return PROGRAM_TEMPLATE.substitute(
        mutable=_format_file_list(marker.target.mutable),
        immutable=_format_file_list(marker.target.immutable),
        metric_command=marker.metric.command,
        metric_extract=marker.metric.extract,
        direction=marker.metric.direction.value,
        baseline_line=baseline_line,
        target_line=target_line,
        budget=marker.agent.budget_per_experiment,
        issues_section=issues_section,
        escalation_section=_escalation_instructions(escalation_level),
        results_section=_format_results_section(results_summary),
        ideas_section=_format_ideas_section(ideas_content),
    )


def _fetch_issues(marker: Marker, repo_path: Path | None) -> str:
    """Fetch specific issues from the metric system to guide the agent."""
    cmd = marker.metric.issues_command
    if not cmd:
        return "Find and fix issues that will improve the metric.\n\n"

    try:
        result = subprocess.run(
            ["bash", "-c", cmd],
            cwd=repo_path or Path("."),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0 and result.stdout.strip():
            issues = result.stdout.strip()
            logger.info(f"Fetched issues for agent: {issues.count(chr(10)) + 1} lines")
            return f"## Specific Issues to Fix\nThese are the EXACT issues from the metric system. Fix these — do not explore broadly.\n\n```\n{issues}\n```\n\n"
        logger.warning(f"Issues command returned no output (rc={result.returncode})")
    except subprocess.TimeoutExpired:
        logger.warning("Issues command timed out (60s)")
    except Exception as e:
        logger.warning(f"Issues command failed: {e}")

    return "Find and fix issues that will improve the metric.\n\n"


def _format_file_list(files: list[str]) -> str:
    """Format a file list as bullet points."""
    if not files:
        return "- (none)"
    return "\n".join(f"- {f}" for f in files)


def _escalation_instructions(level: str) -> str:
    """Return directive text for the current escalation level."""
    if level == "normal":
        return ""

    directives = {
        "refine": (
            "## REFINE Directive\n"
            "Your recent experiments have failed consecutively. "
            "Adjust your strategy within the current approach. "
            "Read the ideas backlog below for alternative angles on the same direction. "
            "Do NOT abandon the current approach yet.\n\n"
        ),
        "pivot": (
            "## PIVOT Directive\n"
            "Multiple consecutive failures. Abandon your current approach entirely. "
            "Pick a fundamentally different direction. "
            "Review the ideas backlog for unexplored approaches and near-misses.\n\n"
        ),
        "search": (
            "## SEARCH Directive\n"
            "Multiple pivots without progress. Before attempting code changes, "
            "research external solutions. Search for papers, patterns, blog posts, "
            "and proven approaches. Append your findings to the ideas backlog "
            "before making any edits.\n\n"
        ),
    }
    return directives.get(level, "")


def _format_results_section(results_summary: str) -> str:
    """Format the results history section."""
    if not results_summary:
        return ""
    lines = results_summary.strip().splitlines()
    if len(lines) > 20:
        lines = lines[-20:]
        truncated = "(showing last 20 experiments)\n"
    else:
        truncated = ""
    content = "\n".join(lines)
    return f"## Results History\n{truncated}{content}\n\n"


def _format_ideas_section(ideas_content: str) -> str:
    """Format the ideas backlog section."""
    if not ideas_content.strip():
        return ""
    return f"## Ideas Backlog\n{ideas_content}\n\n"
