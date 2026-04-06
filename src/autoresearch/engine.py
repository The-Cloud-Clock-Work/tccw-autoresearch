"""Core experiment loop engine."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from autoresearch.ideas import append_idea, read_ideas
from autoresearch.marker import Marker, MarkerStatus
from autoresearch.metrics import (
    compute_confidence,
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
from autoresearch.state import AppState, TrackedMarker, update_state
from autoresearch.utils import parse_duration
from autoresearch.worktree import (
    GitError,
    create_worktree,
    git_commit,
    git_head_short,  # noqa: F401 — used by test mocks via autoresearch.engine.git_head_short
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
    auto_merged: bool = False
    merge_target: str | None = None
    gate_chain_summary: str | None = None


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
        self.marker = marker
        self.agent_config = marker.agent

    def invoke(
        self,
        worktree_path: Path,
        program: str,
        budget: str,
    ) -> AgentResult:
        from autoresearch.agent_profile import DEFAULT_AGENT_DIR, build_cli_permission_flags, ensure_agent_dir
        from autoresearch.telemetry import (
            extract_description_from_telemetry,
            parse_stream_json,
            save_telemetry_report,
        )

        if not shutil.which("claude"):
            raise AgentError("'claude' CLI not found on PATH")

        paths = ensure_agent_dir(worktree_path, self.marker.name, self.marker)
        timeout_seconds = _parse_budget(budget)

        cmd = self._build_cmd(program, worktree_path, paths, DEFAULT_AGENT_DIR, build_cli_permission_flags)
        env = self._build_env(paths, timeout_seconds)

        logger.info(f"Agent cmd: {' '.join(cmd[:6])}...")
        logger.debug(f"Agent cwd: {paths.agent_dir}")
        try:
            result = subprocess.run(
                cmd,
                cwd=str(paths.agent_dir),  # run FROM the agent dir
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                errors="replace",
                env=env,
            )
            output = result.stdout or ""
            if result.returncode != 0:
                logger.warning(f"Agent exit code {result.returncode}: {(result.stderr or '')[:500]}")

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

    def _build_cmd(
        self,
        program: str,
        worktree_path: Path,
        paths,
        default_agent_dir,
        build_cli_permission_flags,
    ) -> list[str]:
        """Build the claude CLI command list."""
        model = self.agent_config.model or self.marker.loop.model or "sonnet"
        default_claude_md = default_agent_dir / "CLAUDE.md"

        cmd = [
            "claude", "-p", program,
            "--model", model,
            "--permission-mode", self.agent_config.permission_mode,
            "--add-dir", str(worktree_path),
            "--output-format", "stream-json",
            "--verbose",
            "--debug-file", str(paths.debug_log_path),
        ]

        if default_claude_md.is_file():
            cmd.extend(["--append-system-prompt-file", str(default_claude_md)])

        if self.agent_config.effort:
            cmd.extend(["--effort", self.agent_config.effort])

        allowed_tools, disallowed_tools = build_cli_permission_flags(self.marker, worktree_path)
        if allowed_tools:
            cmd.extend(["--allowedTools", *allowed_tools])
        if disallowed_tools:
            cmd.extend(["--disallowedTools", *disallowed_tools])

        cmd.extend(self.agent_config.extra_flags)
        return cmd

    def _build_env(self, paths, timeout_seconds: int) -> dict[str, str]:
        """Build the environment dict for the agent subprocess."""
        env = dict(os.environ)
        if paths.env:
            env.update(paths.env)

        dot_env = paths.agent_dir / ".env"
        if dot_env.is_file():
            for line in dot_env.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    env[key.strip()] = value.strip()

        env["AUTORESEARCH_BUDGET_END"] = str(int(time.time()) + timeout_seconds)
        return env


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
            snapshot_ref = _run_snapshot(repo_path, marker, exp_num)

            # Check for HALT
            if esc.escalation_level == "halt":
                logger.warning(f"HALT — {esc.total_pivots} PIVOTs exhausted, needs human")
                final_status = "halted"
                break

            # Generate program and invoke agent
            agent_result, commit_hash = _run_agent_step(
                wt_info.path, repo_path, marker, agent_runner, results, current_best, esc,
            )

            if commit_hash is None:
                discarded += 1
                results = read_results(wt_info.path, marker.name)
                logger.info(f"Exp {exp_num}: discard (no changes)")
                continue

            # Run harness to get new metric
            timeout_sec = _parse_budget(marker.loop.budget_per_experiment)
            harness_result = run_harness(
                marker.metric.command,
                marker.metric.extract,
                wt_info.path,
                marker.name,
                timeout_seconds=timeout_sec,
            )

            if harness_result.metric is None:
                crashed += 1
                esc.on_crash()
                _reset_to_before_commit(wt_info.path, commit_hash)
                _run_restore(repo_path, marker, snapshot_ref)
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

            # Gate 1: metric gate
            if not is_improved(new_metric, current_best, marker.metric.direction.value):
                _record_discard_metric(
                    wt_info.path, repo_path, marker, agent_result, commit_hash,
                    new_metric, snapshot_ref, esc,
                )
                discarded += 1
                results = read_results(wt_info.path, marker.name)
                logger.info(f"Exp {exp_num}: discard (metric {new_metric} not better than {current_best})")
                continue

            # Gate 2: guard gate
            guard_status = _run_guard_gate(
                wt_info.path, repo_path, marker, agent_runner,
                commit_hash, new_metric, snapshot_ref, timeout_sec, agent_result, esc,
            )

            if guard_status is None:
                discarded += 1
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
        # Atomic read-modify-write: reload state from disk so we don't
        # overwrite markers added/removed by the CLI during the run.
        _final_kept = kept
        _final_discarded = discarded
        _final_crashed = crashed
        _final_best = current_best
        _final_branch = wt_info.branch
        _final_wt = str(wt_info.path)
        _final_halted = final_status == "halted"
        _final_time = datetime.now(timezone.utc).isoformat()
        _marker_id = tracked.id

        def _apply_run_results(fresh_state: AppState) -> None:
            for m in fresh_state.markers:
                if m.id == _marker_id:
                    m.last_run_experiments = _final_kept + _final_discarded + _final_crashed
                    m.last_run_kept = _final_kept
                    m.last_run_discarded = _final_discarded
                    m.current = _final_best
                    m.branch = _final_branch
                    m.worktree_path = _final_wt
                    if _final_halted:
                        m.status_override = MarkerStatus.NEEDS_HUMAN
                    m.last_run = _final_time
                    break

        update_state(_apply_run_results, state_path)

        if cleanup_worktree:
            try:
                remove_worktree(repo_path, wt_info.path)
            except GitError:
                logger.warning(f"Failed to cleanup worktree at {wt_info.path}")

    # Compute final confidence
    final_kept = get_kept_metrics(results)
    final_conf = compute_confidence(final_kept, marker.metric.baseline, current_best)

    result = RunResult(
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

    # Post-run: push branch + create PRs for audit trail (always, when kept > 0)
    if result.kept > 0:
        try:
            _publish_results(repo_path, marker, result, wt_info.branch, results)
        except Exception:
            logger.exception("Failed to publish results")

    return result


def _publish_results(
    repo_path: Path,
    marker: "Marker",
    result: RunResult,
    source_branch: str,
    _results: list,
) -> None:
    """Push branch, create PR to dev (auto-merge), optionally PR to main.

    This runs for EVERY kept experiment — it's the audit trail.
    Every improvement gets a GitHub PR with diff, description, and metric delta.
    """
    if not shutil.which("gh"):
        logger.warning("gh CLI not found — skipping PR creation")
        return

    target = marker.auto_merge.target_branch or "dev"

    # 1. Push the experiment branch to GitHub
    logger.info(f"Pushing branch {source_branch} to origin")
    push_result = subprocess.run(
        ["git", "push", "origin", source_branch],
        cwd=repo_path, capture_output=True, text=True, timeout=60,
    )
    if push_result.returncode != 0:
        logger.warning(f"Push failed: {push_result.stderr[:200]}")
        return

    # 2. Ensure target branch exists on remote
    check_branch = subprocess.run(
        ["git", "ls-remote", "--heads", "origin", target],
        cwd=repo_path, capture_output=True, text=True, timeout=15,
    )
    if not check_branch.stdout.strip():
        logger.info(f"Target branch '{target}' not on remote — creating from HEAD")
        subprocess.run(
            ["git", "branch", target],
            cwd=repo_path, capture_output=True, text=True,
        )
        subprocess.run(
            ["git", "push", "origin", target],
            cwd=repo_path, capture_output=True, text=True, timeout=30,
        )

    # 3. Create PR: experiment branch → target (auto-merge via gh)
    title = f"[autoresearch] {marker.name}: {result.kept} fix(es), {result.final_metric} errors"
    body = (
        f"## Autoresearch Experiment\n\n"
        f"**Marker:** {marker.name}\n"
        f"**Metric:** {marker.metric.baseline} → {result.final_metric} "
        f"({marker.metric.direction.value})\n"
        f"**Experiments:** {result.experiments} total, "
        f"{result.kept} kept, {result.discarded} discarded\n"
        f"**Status:** KEEP\n\n"
        f"---\n"
        f"Auto-generated by autoresearch engine."
    )

    pr_cmd = subprocess.run(
        ["gh", "pr", "create", "--base", target, "--head", source_branch,
         "--title", title, "--body", body],
        cwd=repo_path, capture_output=True, text=True, timeout=30,
    )

    if pr_cmd.returncode == 0:
        pr_url = pr_cmd.stdout.strip()
        logger.info(f"PR created: {pr_url}")

        # 3. Auto-merge the PR to dev (squash to keep history clean)
        pr_number = pr_url.rstrip("/").split("/")[-1]
        merge_cmd = subprocess.run(
            ["gh", "pr", "merge", pr_number, "--squash", "--auto",
             "--delete-branch=false"],
            cwd=repo_path, capture_output=True, text=True, timeout=30,
        )
        if merge_cmd.returncode == 0:
            result.auto_merged = True
            result.merge_target = target
            logger.info(f"PR #{pr_number} auto-merge enabled to {target}")
        else:
            # Auto-merge may not be available — try direct merge
            merge_cmd2 = subprocess.run(
                ["gh", "pr", "merge", pr_number, "--squash"],
                cwd=repo_path, capture_output=True, text=True, timeout=30,
            )
            if merge_cmd2.returncode == 0:
                result.auto_merged = True
                result.merge_target = target
                logger.info(f"PR #{pr_number} merged to {target}")
            else:
                logger.warning(f"PR merge failed: {merge_cmd2.stderr[:200]}")
    elif "already exists" in pr_cmd.stderr:
        logger.info("PR already exists for this branch")
    else:
        logger.warning(f"PR creation failed: {pr_cmd.stderr[:200]}")

    # 4. If target is dev, also create a promotion PR: dev → main (no auto-merge)
    if target != "main" and result.auto_merged:
        _create_promotion_pr(repo_path, marker, result, source=target, target="main")

    # 5. Close the feedback loop
    _run_state_update(repo_path)


def _run_state_update(repo_path: Path) -> None:
    """Run state-update.sh to close the feedback loop after merge."""
    script = repo_path / "automation" / "state-update.sh"
    if not script.exists():
        logger.debug(f"No state-update.sh found at {script}")
        return
    try:
        subprocess.run(
            ["bash", str(script), str(repo_path)],
            cwd=repo_path, capture_output=True, text=True, timeout=30,
        )
        logger.info("State update completed — feedback loop closed")
    except Exception:
        logger.warning("state-update.sh failed — feedback loop open")


def _create_promotion_pr(
    repo_path: Path,
    marker: "Marker",
    result: RunResult,
    source: str = "dev",
    target: str = "main",
) -> None:
    """Create a GitHub PR from source → target for operator approval.

    The system merges freely to dev, but main requires human approval.
    This creates the PR automatically — operator clicks approve to merge.
    """
    try:
        title = f"[autoresearch] {marker.name}: {result.kept} improvements ({result.final_metric})"
        body = (
            f"## Autoresearch Auto-Promotion\n\n"
            f"**Marker:** {marker.name}\n"
            f"**Experiments:** {result.experiments} total, {result.kept} kept, {result.discarded} discarded\n"
            f"**Metric:** {marker.metric.baseline} → {result.final_metric} ({marker.metric.direction.value})\n"
            f"**Confidence:** {result.final_confidence}\n"
            f"**Gate chain:** {result.gate_chain_summary}\n\n"
            f"Auto-merged to `{source}`. Approve this PR to promote to `{target}`.\n\n"
            f"---\n"
            f"Generated by autoresearch engine"
        )

        pr_result = subprocess.run(
            ["gh", "pr", "create", "--base", target, "--head", source,
             "--title", title, "--body", body],
            cwd=repo_path, capture_output=True, text=True, timeout=30,
        )

        if pr_result.returncode == 0:
            pr_url = pr_result.stdout.strip()
            logger.info(f"Promotion PR created: {pr_url}")
        else:
            # PR may already exist
            if "already exists" in pr_result.stderr:
                logger.info("Promotion PR already exists — skipping")
            else:
                logger.warning(f"PR creation failed: {pr_result.stderr[:200]}")

    except Exception:
        logger.exception("Failed to create promotion PR")


def _run_agent_step(
    worktree_path: Path,
    repo_path: Path,
    marker: Marker,
    agent_runner: AgentRunner,
    results: list,
    current_best: float,
    esc: EscalationState,
) -> tuple[AgentResult, str | None]:
    """Generate a program, invoke the agent, and commit any changes.

    Returns (agent_result, commit_hash).  commit_hash is None when no
    changes were made or the agent failed without producing a diff.
    """
    results_summary = _format_results_for_program(results)
    ideas_content = read_ideas(worktree_path, marker.name)
    program = generate_program(
        marker, current_best, results_summary, ideas_content, esc.escalation_level,
        repo_path=repo_path,
    )

    head_before = git_head_short(worktree_path)

    agent_result = agent_runner.invoke(
        worktree_path, program, marker.loop.budget_per_experiment
    )

    commit_hash = git_commit(worktree_path, agent_result.description or "experiment")

    # If agent already committed, git_commit finds nothing staged and returns "".
    # Detect this by checking if HEAD moved during the agent run.
    if not commit_hash:
        head_after = git_head_short(worktree_path)
        if head_after != head_before:
            commit_hash = head_after
            logger.info(f"Agent committed directly: {commit_hash}")

    if not commit_hash:
        esc.on_discard()
        append_result(worktree_path, marker.name, ExperimentResult(
            commit="-------",
            metric=0,
            guard="--",
            status="discard",
            confidence="--",
            description=agent_result.description or "no changes made",
        ))
        return agent_result, None

    return agent_result, commit_hash


def _record_discard_metric(
    worktree_path: Path,
    repo_path: Path,
    marker: Marker,
    agent_result: AgentResult,
    commit_hash: str,
    new_metric: float,
    snapshot_ref: str | None,
    esc: EscalationState,
) -> None:
    """Record a metric-gate discard: reset worktree, write ideas/feedback, append result."""
    esc.on_discard()
    _reset_to_before_commit(worktree_path, commit_hash)
    _run_restore(repo_path, marker, snapshot_ref)
    _write_discard_idea(worktree_path, marker.name, agent_result.description, new_metric)
    _write_telemetry_feedback(worktree_path, marker.name, agent_result)
    append_result(worktree_path, marker.name, ExperimentResult(
        commit=commit_hash,
        metric=new_metric,
        guard="--",
        status="discard",
        confidence="--",
        description=agent_result.description,
    ))


def _run_guard_gate(
    worktree_path: Path,
    repo_path: Path,
    marker: Marker,
    agent_runner: AgentRunner,
    commit_hash: str,
    new_metric: float,
    snapshot_ref: str | None,
    timeout_sec: int,
    agent_result: AgentResult,
    esc: EscalationState,
) -> str | None:
    """Run the guard gate and attempt rework on failure.

    Returns the guard_status string ("pass") on success, or None on failure.
    Side-effects on failure: resets worktree, appends discard result, calls esc.on_discard().
    """
    if not (marker.guard and marker.guard.command):
        return "pass"

    guard_result = run_guard(
        marker.guard.command,
        marker.guard.extract,
        marker.guard.threshold,
        worktree_path,
        timeout_seconds=timeout_sec,
    )

    if guard_result.passed:
        return "pass"

    fixed = _handle_guard_failure(
        worktree_path, marker, agent_runner, guard_result,
        marker.guard.rework_attempts,
    )

    if fixed:
        return "pass"

    esc.on_discard()
    _reset_to_before_commit(worktree_path, commit_hash)
    _run_restore(repo_path, marker, snapshot_ref)
    append_result(worktree_path, marker.name, ExperimentResult(
        commit=commit_hash,
        metric=new_metric,
        guard="fail",
        status="discard",
        confidence="--",
        description=f"{agent_result.description} (guard failed after rework)",
    ))
    return None


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


def _run_snapshot(repo_path: Path, marker: Marker, exp_num: int) -> str | None:
    """Run pre-experiment snapshot command if configured. Returns snapshot ID."""
    cmd = marker.auto_merge.snapshot_command
    if not cmd:
        return None
    try:
        expanded = cmd.replace("{exp_num}", str(exp_num))
        result = subprocess.run(
            ["bash", "-c", expanded],
            cwd=repo_path, capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0:
            snap_id = result.stdout.strip().split("\n")[-1]
            logger.info(f"Pre-experiment snapshot: {snap_id}")
            return snap_id
        logger.warning(f"Snapshot command failed (rc={result.returncode}): {result.stderr[:200]}")
    except subprocess.TimeoutExpired:
        logger.warning("Snapshot command timed out (120s)")
    except Exception as e:
        logger.warning(f"Snapshot command error: {e}")
    return None


def _run_restore(repo_path: Path, marker: Marker, snapshot_ref: str | None) -> None:
    """Run restore command if snapshot exists."""
    cmd = marker.auto_merge.restore_command
    if not cmd or not snapshot_ref:
        return
    try:
        expanded = cmd.replace("{snapshot_id}", snapshot_ref)
        result = subprocess.run(
            ["bash", "-c", expanded],
            cwd=repo_path, capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0:
            logger.info(f"Restore completed for snapshot {snapshot_ref}")
        else:
            logger.warning(f"Restore failed (rc={result.returncode}): {result.stderr[:200]}")
    except subprocess.TimeoutExpired:
        logger.warning("Restore command timed out (120s)")
    except Exception as e:
        logger.warning(f"Restore command error: {e}")


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
            # permission_denials can be list[dict] (from Claude stream-json) or list[str]
            denials = []
            for d in telemetry.permission_denials[:3]:
                if isinstance(d, dict):
                    denials.append(f"{d.get('tool_name', 'unknown')}")
                else:
                    denials.append(str(d))
            summary = "; ".join(denials)
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
