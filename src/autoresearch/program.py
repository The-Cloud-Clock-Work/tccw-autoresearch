"""Program.md template generation from marker config."""

from __future__ import annotations

from string import Template

from autoresearch.marker import Marker


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

## Loop
1. Read current code and results history below
2. Propose a hypothesis (what to change and why)
3. Edit target files
4. git commit with descriptive message
5. Run metric harness: $metric_command > run.log 2>&1
6. Extract result
7. If empty --> crash --> tail -n 50 run.log --> attempt fix or discard
8. Log to results.tsv
9. If improved --> KEEP (branch advances)
10. If equal or worse --> DISCARD (git reset --hard)
11. REPEAT -- NEVER STOP, NEVER ASK HUMAN

## Crash Handling
- Typo/syntax --> fix and retry (same experiment)
- Fundamental failure --> discard, log "crash", move on
- 3 consecutive crashes --> simplify back to last known good

## Time Budget
Each experiment must complete within $budget.
If exceeded --> kill, treat as crash, discard.

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
) -> str:
    """Generate the program.md instruction document from a marker.

    Args:
        marker: The marker configuration.
        current_best: Current best metric value (None if no experiments yet).
        results_summary: Formatted results history (truncated).
        ideas_content: Content from ideas.md.
        escalation_level: Current escalation level (normal/refine/pivot/search/halt).

    Returns:
        Complete program.md content as a string.
    """
    if current_best is not None:
        baseline_line = f"Baseline: {marker.metric.baseline}    Current best: {current_best}"
    else:
        baseline_line = f"Baseline: {marker.metric.baseline} (no experiments yet)"

    target_line = f"Target: {marker.metric.target}" if marker.metric.target else ""

    return PROGRAM_TEMPLATE.substitute(
        mutable=_format_file_list(marker.target.mutable),
        immutable=_format_file_list(marker.target.immutable),
        metric_command=marker.metric.command,
        metric_extract=marker.metric.extract,
        direction=marker.metric.direction.value,
        baseline_line=baseline_line,
        target_line=target_line,
        budget=marker.loop.budget_per_experiment,
        escalation_section=_escalation_instructions(escalation_level),
        results_section=_format_results_section(results_summary),
        ideas_section=_format_ideas_section(ideas_content),
    )


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
