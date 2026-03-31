"""Core experiment loop engine."""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from autoresearch.ideas import append_idea, read_ideas
from autoresearch.marker import Marker, MarkerStatus
from autoresearch.metrics import (
    compute_confidence,
    confidence_label,
    is_improved,
    run_guard,
    run_harness,
)
from autoresearch.program import generate_program
from autoresearch.results import (
    ExperimentResult,
    append_result,
    get_kept_metrics,
    get_latest_metric,
    read_results,
)
from autoresearch.state import AppState, TrackedMarker, save_state
from autoresearch.utils import parse_duration
from autoresearch.worktree import (
    GitError,
    create_worktree,
    git_commit,
    git_head_short,
    git_reset_hard,
    remove_worktree,
)

logger = logging.getLogger(__name__)


class AgentError(Exception):
    """Raised when the agent binary is unavailable or catastrophically fails."""


class EngineError(Exception):
    """Raised for precondition failures (marker not active, bad repo, etc)."""


@dataclass
class AgentResult:
    """What the agent returns after attempting an experiment."""

    success: bool
    description: str
    exit_code: int
    output: str
    telemetry: object | None = None


class AgentRunner(ABC):
    """Interface for invoking an LLM agent within the experiment loop."""

    @abstractmethod
    def invoke(
        self,
        worktree_path: Path,
        program: str,
        budget: str,
    ) -> AgentResult:
        """Run the agent in the worktree with the given program instructions."""
        ...


@dataclass
class RunResult:
    """Summary of a marker run."""

    marker_name: str
    experiments: int
    kept: int
    discarded: int
    crashed: int
    final_metric: float | None
    final_confidence: float | None
    final_status: str  # "completed" | "halted" | "budget_exhausted"
    branch: str
    worktree_path: str


@dataclass
class EscalationState:
    """In-memory state machine for failure escalation within a single run."""

    consecutive_failures: int = 0
    total_pivots: int = 0
    pivots_without_progress: int = 0
    last_kept_experiment: int = 0
    current_experiment: int = 0
    escalation_level: str = "normal"

    refine_after: int = 3
    pivot_after: int = 5
    search_after_pivots: int = 2
    halt_after_pivots: int = 3

    def on_keep(self) -> None:
        """Reset failure tracking on a successful keep."""
        self.consecutive_failures = 0
        self.last_kept_experiment = self.current_experiment
        self.pivots_without_progress = 0
        self.escalation_level = "normal"

    def on_discard(self) -> None:
        """Increment failure tracking on a discard."""
        self.consecutive_failures += 1
        self._evaluate()

    def on_crash(self) -> None:
        """Increment failure tracking on a crash."""
        self.consecutive_failures += 1
        self._evaluate()

    def _evaluate(self) -> None:
        """Re-evaluate escalation level based on current state."""
        if self.consecutive_failures >= self.pivot_after:
            self.total_pivots += 1
            self.pivots_without_progress += 1
            self.consecutive_failures = 0
            if self.total_pivots >= self.halt_after_pivots:
                self.escalation_level = "halt"
            elif self.pivots_without_progress >= self.search_after_pivots:
                self.escalation_level = "search"
                self.pivots_without_progress = 0
            else:
                self.escalation_level = "pivot"
        elif self.consecutive_failures >= self.refine_after:
            self.escalation_level = "refine"
        else:
            self.escalation_level = "normal"


class ClaudeCodeRunner(AgentRunner):
    """Agent runner using Claude Code CLI with profile-based permissions."""

    def __init__(self, marker: "Marker"):
        from autoresearch.marker import Marker  # noqa: F811
        self.marker = marker
        self.agent_config = marker.agent

    def invoke(
        self,
        worktree_path: Path,
        program: str,
        budget: str,
    ) -> AgentResult:
        from autoresearch.agent_profile import ensure_agent_dir
        from autoresearch.telemetry import (
            extract_description_from_telemetry,
            parse_stream_json,
            save_telemetry_report,
        )

        if not shutil.which("claude"):
            raise AgentError("'claude' CLI not found on PATH")

        paths = ensure_agent_dir(worktree_path, self.marker.name, self.marker)
        timeout_seconds = _parse_budget(budget)

        model = self.agent_config.model or self.marker.loop.model or "sonnet"

        # Run claude from the agent dir (inherits CLAUDE.md, .claude/settings, rules, etc.)
        # Use --add-dir to give access to the actual worktree
        cmd = [
            "claude", "-p", program,
            "--model", model,
            "--permission-mode", self.agent_config.permission_mode,
            "--add-dir", str(worktree_path),
            "--output-format", "stream-json",
            "--verbose",
            "--debug-file", str(paths.debug_log_path),
        ]

        if self.agent_config.effort:
            cmd.extend(["--effort", self.agent_config.effort])
        if self.agent_config.allowed_tools:
            cmd.extend(["--allowedTools", *self.agent_config.allowed_tools])
        if self.agent_config.disallowed_tools:
            cmd.extend(["--disallowedTools", *self.agent_config.disallowed_tools])
        cmd.extend(self.agent_config.extra_flags)

        try:
            result = subprocess.run(
                cmd,
                cwd=str(paths.agent_dir),  # run FROM the agent dir
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                errors="replace",
            )
            output = result.stdout or ""

            # Save stream-json log
            if output:
                paths.stream_log_path.write_text(output, errors="replace")

            # Parse telemetry
            telemetry = parse_stream_json(output)
            ts = paths.stream_log_path.stem.replace("run-", "")
            save_telemetry_report(telemetry, paths.logs_dir, ts)

            # Extract description: prefer telemetry, fall back to heuristic
            description = extract_description_from_telemetry(telemetry) or _extract_description(output)

            return AgentResult(
                success=result.returncode == 0,
                description=description,
                exit_code=result.returncode,
                output=output[-4000:],
                telemetry=telemetry,
            )
        except subprocess.TimeoutExpired as e:
            partial = ""
            if e.stdout:
                partial = e.stdout if isinstance(e.stdout, str) else e.stdout.decode(errors="replace")
            return AgentResult(
                success=False,
                description="agent timeout",
                exit_code=-1,
                output=partial[-2000:] if partial else "TIMEOUT",
            )


def get_agent_runner(marker: "Marker") -> AgentRunner:
    """Return the appropriate agent runner for the given marker."""
    return ClaudeCodeRunner(marker=marker)


def run_marker(
    repo_path: Path,
    marker: Marker,
    state: AppState,
    tracked: TrackedMarker,
    agent_runner: AgentRunner,
    state_path: Path | None = None,
    worktree_base: Path | None = None,
    cleanup_worktree: bool = True,
) -> RunResult:
    """Run the experiment loop for a single marker.

    This is THE entry point. CLI and daemon call this.
    """
    if marker.status not in (MarkerStatus.ACTIVE,):
        raise EngineError(f"Marker '{marker.name}' is not active (status: {marker.status.value})")
    if not repo_path.exists():
        raise EngineError(f"Repository path does not exist: {repo_path}")

    # Create worktree
    wt_info = create_worktree(
        repo_path,
        marker.name,
        branch_prefix=marker.results.branch_prefix or "autoresearch",
        worktree_base=worktree_base,
    )
    logger.info(f"Created worktree at {wt_info.path} on branch {wt_info.branch}")

    # Read existing results
    results = read_results(wt_info.path, marker.name)
    latest = get_latest_metric(results)
    current_best = latest if latest is not None else marker.metric.baseline

    # Initialize escalation state
    esc = EscalationState(
        refine_after=marker.escalation.refine_after,
        pivot_after=marker.escalation.pivot_after,
        search_after_pivots=marker.escalation.search_after_pivots,
        halt_after_pivots=marker.escalation.halt_after_pivots,
    )

    kept = 0
    discarded = 0
    crashed = 0
    final_status = "budget_exhausted"
    max_experiments = marker.loop.max_experiments

    try:
        for exp_num in range(1, max_experiments + 1):
            esc.current_experiment = exp_num

            # Check for HALT
            if esc.escalation_level == "halt":
                logger.warning(f"HALT — {esc.total_pivots} PIVOTs exhausted, needs human")
                final_status = "halted"
                break

            # Generate program
            results_summary = _format_results_for_program(results)
            ideas_content = read_ideas(wt_info.path, marker.name)
            program = generate_program(
                marker, current_best, results_summary, ideas_content, esc.escalation_level
            )

            # Invoke agent
            agent_result = agent_runner.invoke(
                wt_info.path, program, marker.loop.budget_per_experiment
            )

            # Commit changes
            commit_hash = ""
            if agent_result.success:
                commit_hash = git_commit(wt_info.path, agent_result.description or "experiment")

            if not commit_hash:
                # No changes made or agent failed
                discarded += 1
                esc.on_discard()
                append_result(wt_info.path, marker.name, ExperimentResult(
                    commit="-------",
                    metric=0,
                    guard="--",
                    status="discard",
                    confidence="--",
                    description=agent_result.description or "no changes made",
                ))
                results = read_results(wt_info.path, marker.name)
                logger.info(f"Exp {exp_num}: discard (no changes)")
                continue

            # Run harness
            timeout_sec = _parse_budget(marker.loop.budget_per_experiment)
            harness_result = run_harness(
                marker.metric.command,
                marker.metric.extract,
                wt_info.path,
                marker.name,
                timeout_seconds=timeout_sec,
            )

            # Crash handling
            if harness_result.metric is None:
                crashed += 1
                esc.on_crash()
                _reset_to_before_commit(wt_info.path, commit_hash)
                append_result(wt_info.path, marker.name, ExperimentResult(
                    commit=commit_hash,
                    metric=0,
                    guard="--",
                    status="crash",
                    confidence="--",
                    description=agent_result.description,
                ))
                results = read_results(wt_info.path, marker.name)
                logger.info(f"Exp {exp_num}: crash")
                continue

            new_metric = harness_result.metric

            # Gate 1: metric improved?
            if not is_improved(new_metric, current_best, marker.metric.direction.value):
                discarded += 1
                esc.on_discard()
                _reset_to_before_commit(wt_info.path, commit_hash)
                _write_discard_idea(wt_info.path, marker.name, agent_result.description, new_metric)
                _write_telemetry_feedback(wt_info.path, marker.name, agent_result)
                append_result(wt_info.path, marker.name, ExperimentResult(
                    commit=commit_hash,
                    metric=new_metric,
                    guard="--",
                    status="discard",
                    confidence="--",
                    description=agent_result.description,
                ))
                results = read_results(wt_info.path, marker.name)
                logger.info(f"Exp {exp_num}: discard (metric {new_metric} not better than {current_best})")
                continue

            # Gate 2: guard passes?
            guard_status = "pass"
            if marker.guard and marker.guard.command:
                guard_result = run_guard(
                    marker.guard.command,
                    marker.guard.extract,
                    marker.guard.threshold,
                    wt_info.path,
                    timeout_seconds=timeout_sec,
                )
                if not guard_result.passed:
                    # Rework loop
                    fixed = _handle_guard_failure(
                        wt_info.path, marker, agent_runner, guard_result,
                        marker.guard.rework_attempts,
                    )
                    if not fixed:
                        discarded += 1
                        esc.on_discard()
                        _reset_to_before_commit(wt_info.path, commit_hash)
                        guard_status = "fail"
                        append_result(wt_info.path, marker.name, ExperimentResult(
                            commit=commit_hash,
                            metric=new_metric,
                            guard="fail",
                            status="discard",
                            confidence="--",
                            description=f"{agent_result.description} (guard failed after rework)",
                        ))
                        results = read_results(wt_info.path, marker.name)
                        logger.info(f"Exp {exp_num}: discard (guard failed)")
                        continue

            # KEEP
            kept += 1
            current_best = new_metric
            esc.on_keep()

            kept_metrics = get_kept_metrics(results) + [new_metric]
            conf = compute_confidence(kept_metrics, marker.metric.baseline, current_best)
            conf_str = f"{conf:.1f}" if conf is not None else "--"

            append_result(wt_info.path, marker.name, ExperimentResult(
                commit=commit_hash,
                metric=new_metric,
                guard=guard_status,
                status="keep",
                confidence=conf_str,
                description=agent_result.description,
            ))
            results = read_results(wt_info.path, marker.name)
            logger.info(f"Exp {exp_num}: KEEP (metric {new_metric}, conf {conf_str})")

            # Check target reached
            if marker.metric.target is not None and _target_reached(marker, current_best):
                final_status = "completed"
                logger.info(f"Target reached: {current_best} vs target {marker.metric.target}")
                break

    finally:
        # Always update state and attempt cleanup, even on exception
        tracked.last_run_experiments = kept + discarded + crashed
        tracked.last_run_kept = kept
        tracked.last_run_discarded = discarded
        tracked.current = current_best
        tracked.branch = wt_info.branch
        tracked.worktree_path = str(wt_info.path)
        if final_status == "halted":
            tracked.status_override = MarkerStatus.NEEDS_HUMAN
        tracked.last_run = datetime.now(timezone.utc).isoformat()

        if state_path:
            save_state(state, state_path)

        if cleanup_worktree:
            try:
                remove_worktree(repo_path, wt_info.path)
            except GitError:
                logger.warning(f"Failed to cleanup worktree at {wt_info.path}")

    # Compute final confidence
    final_kept = get_kept_metrics(results)
    final_conf = compute_confidence(final_kept, marker.metric.baseline, current_best)

    return RunResult(
        marker_name=marker.name,
        experiments=kept + discarded + crashed,
        kept=kept,
        discarded=discarded,
        crashed=crashed,
        final_metric=current_best,
        final_confidence=final_conf,
        final_status=final_status,
        branch=wt_info.branch,
        worktree_path=str(wt_info.path),
    )


def _handle_guard_failure(
    worktree_path: Path,
    marker: Marker,
    agent_runner: AgentRunner,
    guard_result,
    max_attempts: int,
) -> bool:
    """Attempt to fix a guard failure via agent rework.

    Returns True if the guard eventually passes.
    """
    budget = marker.loop.budget_per_experiment
    for attempt in range(max_attempts):
        rework_prompt = (
            f"The guard command failed. Output:\n{guard_result.output[-500:]}\n"
            f"Fix the regression without losing the metric improvement. Attempt {attempt + 1}/{max_attempts}."
        )
        result = agent_runner.invoke(worktree_path, rework_prompt, budget)
        if result.success:
            git_commit(worktree_path, f"rework: fix guard (attempt {attempt + 1})")
            timeout_sec = _parse_budget(marker.loop.budget_per_experiment)
            new_guard = run_guard(
                marker.guard.command,
                marker.guard.extract,
                marker.guard.threshold,
                worktree_path,
                timeout_seconds=timeout_sec,
            )
            if new_guard.passed:
                return True
    return False


def _reset_to_before_commit(worktree_path: Path, commit_hash: str) -> None:
    """Reset to the commit before the given one."""
    try:
        git_reset_hard(worktree_path, f"{commit_hash}~1")
    except GitError as e:
        logger.warning(f"Could not reset to {commit_hash}~1: {e}")


def _target_reached(marker: Marker, current: float) -> bool:
    """Check if the metric target has been reached."""
    if marker.metric.target is None:
        return False
    if marker.metric.direction.value == "higher":
        return current >= marker.metric.target
    return current <= marker.metric.target


def _format_results_for_program(results: list[ExperimentResult]) -> str:
    """Format results history as text for the program template."""
    if not results:
        return ""
    lines = []
    for r in results:
        lines.append(f"{r.commit}\t{r.metric}\t{r.guard}\t{r.status}\t{r.confidence}\t{r.description}")
    return "\n".join(lines)


def _write_discard_idea(
    worktree_path: Path,
    marker_name: str,
    description: str,
    metric: float,
) -> None:
    """Write a discarded-but-promising idea to the ideas backlog."""
    try:
        entry = f"**{description}** (metric: {metric}, discarded)"
        append_idea(worktree_path, marker_name, "Discarded but Promising", entry)
    except (ValueError, OSError):
        pass


def _write_telemetry_feedback(
    worktree_path: Path, marker_name: str, agent_result: AgentResult
) -> None:
    """Write telemetry errors and permission denials to ideas backlog."""
    if not agent_result.telemetry:
        return
    try:
        telemetry = agent_result.telemetry
        if hasattr(telemetry, "errors") and telemetry.errors:
            summary = "; ".join(telemetry.errors[:3])
            append_idea(worktree_path, marker_name, "Discarded but Promising", f"**Agent errors:** {summary}")
        if hasattr(telemetry, "permission_denials") and telemetry.permission_denials:
            summary = "; ".join(telemetry.permission_denials[:3])
            append_idea(worktree_path, marker_name, "Near-Misses", f"**Permission denied:** {summary}")
    except (ValueError, OSError):
        pass


_parse_budget = parse_duration


def _extract_description(output: str) -> str:
    """Extract a description from agent output (last non-metadata line)."""
    lines = output.strip().splitlines() if output else []
    for line in reversed(lines):
        stripped = line.strip()
        if not stripped or len(stripped) < 3:
            continue
        # Skip metadata: timestamps, log prefixes, shell prompts, dividers
        if re.match(r"^(\d{4}-\d{2}|\[.*\]|>>>|===|---|\.\.\.|\$)", stripped):
            continue
        return stripped[:200]
    return "experiment"
