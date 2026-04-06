"""AutoResearch CLI — dual-mode interactive TUI + headless JSON interface."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from autoresearch.cli_utils import (
    err_json,
    headless_output,
    is_headless,
    ok_json,
    render_status,
)
from autoresearch.marker import (
    MarkerStatus,
    find_marker_file,
    get_marker,
    load_markers,
)
from autoresearch.state import (
    get_effective_status,
    get_tracked,
    load_state,
    save_state,
    track_marker,
    untrack_marker,
)

app = typer.Typer(
    name="autoresearch",
    help="Autonomous code improvement engine",
    no_args_is_help=False,
    invoke_without_command=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)

console = Console()

MARKER_ID_HELP = "Marker ID (repo:name)"

# Daemon sub-app
daemon_app = typer.Typer(help="Daemon management commands")
app.add_typer(daemon_app, name="daemon")


def _init_ctx(ctx: typer.Context) -> None:
    """Ensure ctx.obj is populated (for subcommands invoked directly)."""
    if ctx.obj is None:
        ctx.obj = {}


def _load_state(_ctx: typer.Context):
    return load_state()


def _resolve_marker_data(tracked, _config_path=None):
    """Load marker YAML data for a tracked marker. Returns (MarkerFile, Marker, effective_status) or Nones."""
    repo_path = Path(tracked.repo_path)
    mf_path = find_marker_file(repo_path)
    if not mf_path:
        return None, None, None
    try:
        mf = load_markers(mf_path)
    except Exception:
        return None, None, None
    m = get_marker(mf, tracked.marker_name)
    if not m:
        return None, None, None
    eff = get_effective_status(tracked, m.status)
    return mf, m, eff


def _format_tracked_json(tracked, marker, effective_status):
    """Build JSON-serializable dict for a tracked marker."""
    return {
        "id": tracked.id,
        "repo": tracked.repo_name,
        "marker": tracked.marker_name,
        "status": effective_status.value if effective_status else "unknown",
        "last_run": tracked.last_run,
        "experiments": tracked.last_run_experiments,
        "kept": tracked.last_run_kept,
        "discarded": tracked.last_run_discarded,
        "baseline": tracked.baseline,
        "current": tracked.current,
        "branch": tracked.branch,
    }


def _render_marker_table(markers_data: list[dict]) -> None:
    """Render tracked markers as a rich table."""
    table = Table(title="AutoResearch", show_lines=False)
    table.add_column("#", style="dim", width=4)
    table.add_column("Repo")
    table.add_column("Marker")
    table.add_column("Status")
    table.add_column("Last Run", justify="right")
    table.add_column("Current", justify="right")

    for i, md in enumerate(markers_data, 1):
        status_str = md.get("status", "unknown")
        try:
            ms = MarkerStatus(status_str)
            status_text = render_status(ms)
        except ValueError:
            status_text = status_str

        table.add_row(
            str(i),
            md.get("repo", ""),
            md.get("marker", ""),
            status_text,
            md.get("last_run") or "--",
            str(md.get("current")) if md.get("current") is not None else "--",
        )

    console.print(table)


# ---------------------------------------------------------------------------
# Root callback — global flags + interactive dispatch
# ---------------------------------------------------------------------------

@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    headless: bool = typer.Option(False, "--headless", help="JSON output, no prompts"),
    verbose: bool = typer.Option(False, "--verbose", help="Extended debug output"),
    config: Optional[Path] = typer.Option(None, "--config", help="Override config path"),
):
    ctx.ensure_object(dict)
    ctx.obj["headless"] = headless
    ctx.obj["verbose"] = verbose
    ctx.obj["config_path"] = config

    if ctx.invoked_subcommand is None:
        if headless:
            headless_output(ctx, err_json("No command specified. Use --help for available commands.", 2))
            raise typer.Exit(code=2)
        _interactive_main(ctx)


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

@app.command("list")
def list_cmd(ctx: typer.Context):
    """List all tracked markers."""
    _init_ctx(ctx)
    state = _load_state(ctx)
    markers_data = []

    for tracked in state.markers:
        _mf, m, eff = _resolve_marker_data(tracked)
        if m and eff:
            markers_data.append(_format_tracked_json(tracked, m, eff))
        else:
            markers_data.append({
                "id": tracked.id,
                "repo": tracked.repo_name,
                "marker": tracked.marker_name,
                "status": "unknown",
                "last_run": tracked.last_run,
                "experiments": tracked.last_run_experiments,
                "kept": tracked.last_run_kept,
                "discarded": tracked.last_run_discarded,
                "baseline": tracked.baseline,
                "current": tracked.current,
                "branch": tracked.branch,
            })

    if is_headless(ctx):
        headless_output(ctx, ok_json(markers_data))
    else:
        if not markers_data:
            console.print("[dim]No markers tracked. Use [bold]autoresearch add[/bold] to register markers.[/dim]")
        else:
            _render_marker_table(markers_data)


@app.command("status")
def status_cmd(
    ctx: typer.Context,
    marker: str = typer.Option(..., "--marker", "-m", help=MARKER_ID_HELP),
):
    """Show detailed status for a marker."""
    _init_ctx(ctx)
    state = _load_state(ctx)
    tracked = get_tracked(state, marker)
    if not tracked:
        if is_headless(ctx):
            headless_output(ctx, err_json(f"Marker not found: {marker}"))
            raise typer.Exit(code=1)
        console.print(f"[red]Marker not found: {marker}[/red]")
        raise typer.Exit(code=1)

    _mf, m, eff = _resolve_marker_data(tracked)
    data = _format_tracked_json(tracked, m, eff)

    if m:
        data["description"] = m.description
        data["direction"] = m.metric.direction.value
        data["target_metric"] = m.metric.target
        data["mutable_files"] = m.target.mutable
        data["budget"] = m.loop.budget_per_experiment
        data["max_experiments"] = m.loop.max_experiments

    if is_headless(ctx):
        headless_output(ctx, ok_json(data))
    else:
        for k, v in data.items():
            console.print(f"  [bold]{k}:[/bold] {v}")


@app.command("results")
def results_cmd(
    ctx: typer.Context,
    marker: str = typer.Option(..., "--marker", "-m", help=MARKER_ID_HELP),
):
    """Show experiment results for a marker."""
    _init_ctx(ctx)
    from autoresearch.results import read_results

    state = _load_state(ctx)
    tracked = get_tracked(state, marker)
    if not tracked:
        if is_headless(ctx):
            headless_output(ctx, err_json(f"Marker not found: {marker}"))
            raise typer.Exit(code=1)
        console.print(f"[red]Marker not found: {marker}[/red]")
        raise typer.Exit(code=1)

    results = read_results(Path(tracked.repo_path), tracked.marker_name)
    results_data = [r.model_dump() for r in results]

    if is_headless(ctx):
        headless_output(ctx, ok_json(results_data))
    else:
        if not results:
            console.print("[dim]No results yet.[/dim]")
        else:
            _show_results_interactive(tracked)


@app.command("ideas")
def ideas_cmd(
    ctx: typer.Context,
    marker: str = typer.Option(..., "--marker", "-m", help=MARKER_ID_HELP),
):
    """Show ideas backlog for a marker."""
    _init_ctx(ctx)
    from autoresearch.ideas import read_ideas

    state = _load_state(ctx)
    tracked = get_tracked(state, marker)
    if not tracked:
        if is_headless(ctx):
            headless_output(ctx, err_json(f"Marker not found: {marker}"))
            raise typer.Exit(code=1)
        console.print(f"[red]Marker not found: {marker}[/red]")
        raise typer.Exit(code=1)

    content = read_ideas(Path(tracked.repo_path), tracked.marker_name)

    if is_headless(ctx):
        headless_output(ctx, ok_json({"ideas": content}))
    else:
        if content.strip():
            console.print(content)
        else:
            console.print("[dim]No ideas logged yet.[/dim]")


@app.command("confidence")
def confidence_cmd(
    ctx: typer.Context,
    marker: str = typer.Option(..., "--marker", "-m", help=MARKER_ID_HELP),
):
    """Show confidence score for a marker."""
    _init_ctx(ctx)
    from autoresearch.metrics import compute_confidence, confidence_label
    from autoresearch.results import get_kept_metrics, read_results

    state = _load_state(ctx)
    tracked = get_tracked(state, marker)
    if not tracked:
        if is_headless(ctx):
            headless_output(ctx, err_json(f"Marker not found: {marker}"))
            raise typer.Exit(code=1)
        console.print(f"[red]Marker not found: {marker}[/red]")
        raise typer.Exit(code=1)

    results = read_results(Path(tracked.repo_path), tracked.marker_name)
    kept = get_kept_metrics(results)

    score = None
    label = "--"
    if tracked.baseline is not None and tracked.current is not None:
        score = compute_confidence(kept, tracked.baseline, tracked.current)
        label = confidence_label(score)

    data = {
        "marker": tracked.id,
        "baseline": tracked.baseline,
        "current": tracked.current,
        "kept_count": len(kept),
        "confidence_score": score,
        "confidence_label": label,
    }

    if is_headless(ctx):
        headless_output(ctx, ok_json(data))
    else:
        console.print(f"[bold]Confidence:[/bold] {label}" + (f" ({score:.2f})" if score else ""))


@app.command("init")
def init_cmd(
    ctx: typer.Context,
    path: Path = typer.Option(".", "--path", help="Repo path (default: current directory)"),
    no_claude: bool = typer.Option(False, "--no-claude", help="Skip Claude onboard wizard, scaffold only"),
    model: str = typer.Option("opus", "--model", help="Claude model for onboard wizard"),
):
    """Initialize .autoresearch/ in a repo and launch the Claude onboard wizard.

    Scaffolds the default agent profile + config template, then spawns an
    interactive Claude Code session with the /onboard skill to walk you through
    marker configuration. Use --no-claude for headless/scaffolding-only mode.
    """
    _init_ctx(ctx)
    import shutil
    import subprocess

    from autoresearch.agent_profile import init_autoresearch_dir
    from autoresearch.marker import CONFIG_DIR, CONFIG_FILENAME

    repo_path = path.resolve()
    ar_dir = repo_path / CONFIG_DIR
    config_path = ar_dir / CONFIG_FILENAME

    already_has_config = config_path.is_file()

    # Always sync agent files (additive, never overwrites)
    ar_dir = init_autoresearch_dir(repo_path)

    # Only write template config if it doesn't exist
    if not already_has_config:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(CONFIG_TEMPLATE)

    if is_headless(ctx) or no_claude:
        # Headless / no-claude: scaffold only, print instructions
        if is_headless(ctx):
            headless_output(ctx, ok_json({
                "path": str(ar_dir),
                "config": str(config_path),
                "agents_dir": str(ar_dir / "agents"),
                "config_created": not already_has_config,
            }))
        else:
            if already_has_config:
                console.print(f"[green]Synced agent files in {ar_dir}[/green]")
            else:
                console.print(f"[green]Initialized .autoresearch/ in {repo_path}[/green]")
            console.print(f"  Config: {config_path}" + (" [dim](already existed)[/dim]" if already_has_config else ""))
            console.print(f"  Agent:  {ar_dir / 'agents' / 'default'}/")
            console.print()
            console.print("[dim]Edit config.yaml to configure your markers.[/dim]")
            console.print("[dim]Duplicate agents/default/ to create custom agents.[/dim]")
        return

    # Interactive: spawn Claude with /onboard skill
    if not shutil.which("claude"):
        console.print("[yellow]claude CLI not found on PATH — falling back to scaffold-only mode.[/yellow]")
        console.print(f"[green]Initialized .autoresearch/ in {repo_path}[/green]")
        console.print(f"  Config: {config_path}")
        console.print()
        console.print("[dim]Install Claude Code (https://docs.anthropic.com/en/docs/claude-code) for the interactive onboard wizard.[/dim]")
        return

    # Package root has .claude/skills/ — Claude discovers /onboard from CWD
    package_root = Path(__file__).parent
    if not (package_root / ".claude" / "skills").exists():
        console.print("[yellow]Skills directory not found in package — falling back to scaffold-only mode.[/yellow]")
        return

    console.print(f"[green]Scaffolded .autoresearch/ in {repo_path}[/green]")
    console.print()
    console.print("[bold]Launching Claude onboard wizard...[/bold]")
    console.print()

    cmd = [
        "claude",
        "--model", model,
        "--add-dir", str(repo_path),
        f"/onboard {repo_path}",
    ]
    subprocess.run(cmd, cwd=str(package_root))


CONFIG_TEMPLATE = """\
markers:
  - name: my-marker
    description: "Describe what this marker improves"
    status: active
    target:
      mutable:
        - src/**/*.py
      immutable:
        - tests/**/*.py
    metric:
      command: "echo 'your metric command here'"
      extract: '(\\d+)'
      direction: higher
      baseline: 0
    guard:
      command: "echo 'your guard command here'"
      extract: '(\\d+)'
      threshold: 0
      rework_attempts: 2
    loop:
      model: sonnet
      budget_per_experiment: 25m
      max_experiments: 10
    agent:
      name: default
      model: sonnet
      effort: medium
      permission_mode: bypassPermissions
      allowed_tools: []
      disallowed_tools: []
    auto_merge:
      enabled: false
      target_branch: dev
    schedule:
      type: on-demand
"""


@app.command("add")
def add_cmd(
    ctx: typer.Context,
    path: Path = typer.Option(..., "--path", help="Path to repo containing .autoresearch/config.yaml"),
):
    """Register markers from a repo."""
    _init_ctx(ctx)
    repo_path = path.resolve()
    mf_path = find_marker_file(repo_path)
    if not mf_path:
        if is_headless(ctx):
            headless_output(ctx, err_json(f"No .autoresearch/config.yaml found in {repo_path}"))
            raise typer.Exit(code=1)
        console.print(f"[red]No .autoresearch/config.yaml found in {repo_path}[/red]")
        raise typer.Exit(code=1)

    try:
        mf = load_markers(mf_path)
    except Exception as e:
        if is_headless(ctx):
            headless_output(ctx, err_json(f"Error reading marker file: {e}"))
            raise typer.Exit(code=1)
        console.print(f"[red]Error reading marker file: {e}[/red]")
        raise typer.Exit(code=1)

    state = _load_state(ctx)
    added = []
    for m in mf.markers:
        tracked = track_marker(state, repo_path, m)
        added.append(tracked.id)
    save_state(state)

    if is_headless(ctx):
        headless_output(ctx, ok_json({"added": added}))
    else:
        console.print(f"[green]Registered {len(added)} marker(s): {', '.join(added)}[/green]")


@app.command("detach")
def detach_cmd(
    ctx: typer.Context,
    marker: str = typer.Option(..., "--marker", "-m", help="Marker ID to detach"),
):
    """Untrack a marker."""
    _init_ctx(ctx)
    state = _load_state(ctx)
    tracked = get_tracked(state, marker)
    if not tracked:
        if is_headless(ctx):
            headless_output(ctx, err_json(f"Marker not found: {marker}"))
            raise typer.Exit(code=1)
        console.print(f"[red]Marker not found: {marker}[/red]")
        raise typer.Exit(code=1)

    untrack_marker(state, marker)
    save_state(state)

    if is_headless(ctx):
        headless_output(ctx, ok_json({"detached": marker}))
    else:
        console.print(f"[yellow]Detached {marker}[/yellow]")


@app.command("skip")
def skip_cmd(
    ctx: typer.Context,
    marker: str = typer.Option(..., "--marker", "-m", help="Marker ID to skip/unskip"),
):
    """Toggle skip status on a marker."""
    _init_ctx(ctx)
    state = _load_state(ctx)
    tracked = get_tracked(state, marker)
    if not tracked:
        if is_headless(ctx):
            headless_output(ctx, err_json(f"Marker not found: {marker}"))
            raise typer.Exit(code=1)
        console.print(f"[red]Marker not found: {marker}[/red]")
        raise typer.Exit(code=1)

    if tracked.status_override == MarkerStatus.SKIP:
        tracked.status_override = None
        new_status = "unskipped"
    else:
        tracked.status_override = MarkerStatus.SKIP
        new_status = "skipped"
    save_state(state)

    if is_headless(ctx):
        headless_output(ctx, ok_json({"marker": marker, "action": new_status}))
    else:
        console.print(f"[yellow]{marker}: {new_status}[/yellow]")


@app.command("pause")
def pause_cmd(
    ctx: typer.Context,
    marker: str = typer.Option(..., "--marker", "-m", help="Marker ID to pause/resume"),
):
    """Toggle pause status on a marker."""
    _init_ctx(ctx)
    state = _load_state(ctx)
    tracked = get_tracked(state, marker)
    if not tracked:
        if is_headless(ctx):
            headless_output(ctx, err_json(f"Marker not found: {marker}"))
            raise typer.Exit(code=1)
        console.print(f"[red]Marker not found: {marker}[/red]")
        raise typer.Exit(code=1)

    if tracked.status_override == MarkerStatus.PAUSED:
        tracked.status_override = None
        new_status = "resumed"
    else:
        tracked.status_override = MarkerStatus.PAUSED
        new_status = "paused"
    save_state(state)

    if is_headless(ctx):
        headless_output(ctx, ok_json({"marker": marker, "action": new_status}))
    else:
        console.print(f"[yellow]{marker}: {new_status}[/yellow]")


def _resolve_run_targets(ctx: typer.Context, state, marker: Optional[str], repo: Optional[str]) -> list:
    """Resolve the list of tracked markers to run, or raise typer.Exit on error."""
    if marker:
        tracked = get_tracked(state, marker)
        if not tracked:
            if is_headless(ctx):
                headless_output(ctx, err_json(f"Marker not found: {marker}"))
                raise typer.Exit(code=1)
            console.print(f"[red]Marker not found: {marker}[/red]")
            raise typer.Exit(code=1)
        return [tracked]
    # repo branch
    to_run = [t for t in state.markers if t.repo_name == repo]
    if not to_run:
        if is_headless(ctx):
            headless_output(ctx, err_json(f"No markers found for repo: {repo}"))
            raise typer.Exit(code=1)
        console.print(f"[red]No markers found for repo: {repo}[/red]")
        raise typer.Exit(code=1)
    return to_run


def _execute_marker_run(t, state, repo: Optional[str], model: Optional[str], auto_merge: Optional[bool]) -> dict:
    """Run a single tracked marker through the engine. Returns a result dict."""
    from autoresearch.engine import EngineError, get_agent_runner, run_marker as engine_run

    _mf, m, eff = _resolve_marker_data(t)
    if not m:
        return {"marker": t.id, "error": "Cannot load marker config"}

    if repo and eff != MarkerStatus.ACTIVE:
        return {}  # sentinel: skip this marker

    if model:
        m.agent.model = model
    if auto_merge is not None:
        m.auto_merge.enabled = auto_merge

    try:
        agent_runner = get_agent_runner(m)
        run_result = engine_run(
            repo_path=Path(t.repo_path),
            marker=m,
            state=state,
            tracked=t,
            agent_runner=agent_runner,
        )
        return {
            "marker": run_result.marker_name,
            "experiments": run_result.experiments,
            "kept": run_result.kept,
            "discarded": run_result.discarded,
            "crashed": run_result.crashed,
            "final_metric": run_result.final_metric,
            "final_confidence": run_result.final_confidence,
            "final_status": run_result.final_status,
            "branch": run_result.branch,
            "auto_merged": run_result.auto_merged,
            "merge_target": run_result.merge_target,
            "gate_chain": run_result.gate_chain_summary,
        }
    except EngineError as e:
        return {"marker": t.id, "error": str(e)}


def _print_run_results(results_list: list) -> None:
    """Print run results to console."""
    for r in results_list:
        if "error" in r:
            console.print(f"[red]{r['marker']}: {r['error']}[/red]")
        else:
            console.print(f"[green]{r['marker']}:[/green] {r['experiments']} experiments, {r['kept']} kept")
            if r.get("gate_chain"):
                console.print(f"  Gate chain: {r['gate_chain']}")
            if r.get("auto_merged"):
                console.print(f"  [green]Auto-merged into {r['merge_target']}[/green]")


@app.command("run")
def run_cmd(
    ctx: typer.Context,
    marker: Optional[str] = typer.Option(None, "--marker", "-m", help="Marker ID to run"),
    repo: Optional[str] = typer.Option(None, "--repo", help="Run all active markers in repo"),
    model: Optional[str] = typer.Option(None, "--model", help="Override LLM model"),
    auto_merge: Optional[bool] = typer.Option(None, "--auto-merge/--no-auto-merge", help="Override auto_merge.enabled"),
):
    """Run experiment loop for a marker or all markers in a repo."""
    _init_ctx(ctx)

    if not marker and not repo:
        if is_headless(ctx):
            headless_output(ctx, err_json("Must specify --marker or --repo", 2))
            raise typer.Exit(code=2)
        console.print("[red]Must specify --marker or --repo[/red]")
        raise typer.Exit(code=2)

    state = _load_state(ctx)
    to_run = _resolve_run_targets(ctx, state, marker, repo)

    results_list = []
    for t in to_run:
        r = _execute_marker_run(t, state, repo, model, auto_merge)
        if r:  # empty dict = skipped (non-active in repo mode)
            results_list.append(r)

    if is_headless(ctx):
        headless_output(ctx, ok_json(results_list))
    else:
        _print_run_results(results_list)


@app.command("finalize")
def finalize_cmd(
    ctx: typer.Context,
    marker: str = typer.Option(..., "--marker", "-m", help="Marker ID to finalize"),
):
    """Cherry-pick and squash kept experiments into clean branches."""
    _init_ctx(ctx)
    from autoresearch.finalize import finalize_marker
    from autoresearch.results import read_results

    state = _load_state(ctx)
    tracked = get_tracked(state, marker)
    if not tracked:
        if is_headless(ctx):
            headless_output(ctx, err_json(f"Marker not found: {marker}"))
            raise typer.Exit(code=1)
        console.print(f"[red]Marker not found: {marker}[/red]")
        raise typer.Exit(code=1)

    results = read_results(Path(tracked.repo_path), tracked.marker_name)
    branches = finalize_marker(
        Path(tracked.repo_path), tracked.marker_name, results, tracked.branch
    )

    if is_headless(ctx):
        headless_output(ctx, ok_json({"branches": branches}))
    else:
        if not branches:
            console.print("[dim]No kept experiments to finalize.[/dim]")
        else:
            console.print(f"[green]Created {len(branches)} finalization branch(es):[/green]")
            for b in branches:
                console.print(f"  {b['branch']} — {b['description']}")


@app.command("merge")
def merge_cmd(
    ctx: typer.Context,
    marker: str = typer.Option(..., "--marker", "-m", help="Marker ID to merge"),
    branch: Optional[str] = typer.Option(None, "--branch", help="Branch to merge (default: marker's branch)"),
    target: str = typer.Option("main", "--target", help="Target branch to merge into"),
):
    """Merge a finalized branch into target."""
    _init_ctx(ctx)
    from autoresearch.finalize import merge_finalized

    state = _load_state(ctx)
    tracked = get_tracked(state, marker)
    if not tracked:
        if is_headless(ctx):
            headless_output(ctx, err_json(f"Marker not found: {marker}"))
            raise typer.Exit(code=1)
        console.print(f"[red]Marker not found: {marker}[/red]")
        raise typer.Exit(code=1)

    merge_branch = branch or tracked.branch
    if not merge_branch:
        if is_headless(ctx):
            headless_output(ctx, err_json("No branch available to merge"))
            raise typer.Exit(code=1)
        console.print("[red]No branch available to merge[/red]")
        raise typer.Exit(code=1)

    try:
        commit = merge_finalized(Path(tracked.repo_path), merge_branch, target)
        if is_headless(ctx):
            headless_output(ctx, ok_json({"merged": merge_branch, "target": target, "commit": commit}))
        else:
            console.print(f"[green]Merged {merge_branch} into {target} ({commit[:7]})[/green]")
    except Exception as e:
        if is_headless(ctx):
            headless_output(ctx, err_json(f"Merge failed: {e}"))
            raise typer.Exit(code=1)
        console.print(f"[red]Merge failed: {e}[/red]")
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# Interactive TUI
# ---------------------------------------------------------------------------

def _build_main_menu(state) -> tuple[list[str], str]:
    """Return (choices, prompt_text) for the main interactive menu."""
    if not state.markers:
        return ["a", "p", "q"], "[a] Add from CWD  [p] Add by path  [q] Quit"
    n = len(state.markers)
    choices = [str(i) for i in range(1, n + 1)] + ["a", "p", "d", "r", "R", "q"]
    prompt_text = f"[1-{n}] Select  [a] Add  [p] Path  [d] Detach  [r] Run  [R] Run repo  [q] Quit"
    return choices, prompt_text


def _dispatch_main_action(ctx: typer.Context, state, action: str, cwd: Path) -> bool:
    """Handle a main-menu action. Returns False to quit, True to continue."""
    from rich.prompt import Prompt

    if action == "q":
        return False
    if action == "a":
        _action_add(ctx, cwd)
    elif action == "p":
        path_str = Prompt.ask("Repo path")
        _action_add(ctx, Path(path_str))
    elif action == "d":
        _action_detach_interactive(ctx, state)
    elif action == "r":
        _action_run_selected_interactive(ctx, state)
    elif action == "R":
        _action_run_repo_interactive(ctx, state)
    elif action.isdigit():
        idx = int(action) - 1
        if 0 <= idx < len(state.markers):
            _marker_submenu(ctx, state.markers[idx])
    return True


def _interactive_main(ctx: typer.Context):
    """Main interactive loop with context-aware views."""
    from rich.prompt import Prompt

    while True:
        state = _load_state(ctx)

        cwd = Path.cwd()
        marker_file_path = find_marker_file(cwd)

        if marker_file_path:
            _repo_mode(ctx, state, cwd, marker_file_path)
        else:
            _home_mode(ctx, state)

        if not state.markers:
            console.print("\n[dim]No markers tracked.[/dim]")

        choices, prompt_text = _build_main_menu(state)
        action = Prompt.ask(f"\n{prompt_text}", choices=choices)
        if not _dispatch_main_action(ctx, state, action, cwd):
            break


def _home_mode(ctx: typer.Context, state):
    """Display all tracked markers (home directory view)."""
    markers_data = []
    for tracked in state.markers:
        _mf, m, eff = _resolve_marker_data(tracked)
        if m and eff:
            markers_data.append(_format_tracked_json(tracked, m, eff))
        else:
            markers_data.append(_format_tracked_json(tracked, None, None))

    if markers_data:
        _render_marker_table(markers_data)


def _repo_mode(ctx: typer.Context, state, cwd: Path, marker_file_path: Path):
    """Display repo-specific view, offer to register untracked markers."""
    from rich.prompt import Prompt

    try:
        mf = load_markers(marker_file_path)
    except Exception as e:
        console.print(f"[red]Error reading {marker_file_path}: {e}[/red]")
        return

    tracked_names = {t.marker_name for t in state.markers if Path(t.repo_path) == cwd}
    untracked = [m for m in mf.markers if m.name not in tracked_names]

    if untracked:
        console.print(f"\n[bold]Found {len(untracked)} untracked marker(s) in {cwd.name}:[/bold]")
        for m in untracked:
            console.print(f"  - {m.name}")
        if Prompt.ask("Register them?", choices=["y", "n"], default="y") == "y":
            for m in untracked:
                track_marker(state, cwd, m)
            save_state(state)
            console.print("[green]Registered.[/green]")

    # Show repo markers as table
    markers_data = []
    for tracked in state.markers:
        if Path(tracked.repo_path) == cwd:
            _mf, marker, eff = _resolve_marker_data(tracked)
            markers_data.append(_format_tracked_json(tracked, marker, eff))
    if markers_data:
        _render_marker_table(markers_data)


def _action_add(ctx: typer.Context, repo_path: Path):
    """Register markers from a repo path."""
    mf_path = find_marker_file(repo_path)
    if not mf_path:
        console.print(f"[red]No .autoresearch/config.yaml found in {repo_path}[/red]")
        return

    try:
        mf = load_markers(mf_path)
    except Exception as e:
        console.print(f"[red]Error reading marker file: {e}[/red]")
        return

    state = _load_state(ctx)
    added = []
    for m in mf.markers:
        tracked = track_marker(state, repo_path.resolve(), m)
        added.append(tracked.id)
    save_state(state)
    console.print(f"[green]Registered {len(added)} marker(s): {', '.join(added)}[/green]")


def _action_detach_interactive(ctx: typer.Context, state):
    from rich.prompt import Prompt

    if not state.markers:
        console.print("[dim]No markers to detach.[/dim]")
        return
    for i, t in enumerate(state.markers, 1):
        console.print(f"  {i}. {t.id}")
    choice = Prompt.ask("Detach #", choices=[str(i) for i in range(1, len(state.markers) + 1)])
    idx = int(choice) - 1
    marker_id = state.markers[idx].id
    untrack_marker(state, marker_id)
    save_state(state)
    console.print(f"[yellow]Detached {marker_id}[/yellow]")


def _action_run_selected_interactive(ctx: typer.Context, state):
    from rich.prompt import Prompt

    if not state.markers:
        console.print("[dim]No markers to run.[/dim]")
        return
    for i, t in enumerate(state.markers, 1):
        console.print(f"  {i}. {t.id}")
    choice = Prompt.ask("Run #", choices=[str(i) for i in range(1, len(state.markers) + 1)])
    idx = int(choice) - 1
    _run_single_marker(ctx, state.markers[idx])


def _action_run_repo_interactive(ctx: typer.Context, state):
    from rich.prompt import Prompt

    repos = sorted({t.repo_name for t in state.markers})
    if not repos:
        console.print("[dim]No repos tracked.[/dim]")
        return
    for i, r in enumerate(repos, 1):
        console.print(f"  {i}. {r}")
    choice = Prompt.ask("Run repo #", choices=[str(i) for i in range(1, len(repos) + 1)])
    repo_name = repos[int(choice) - 1]
    _run_repo_markers(ctx, state, repo_name)


def _run_single_marker(ctx: typer.Context, tracked):
    """Run a single marker through the engine."""
    from autoresearch.engine import EngineError, get_agent_runner, run_marker

    _mf, marker, _ = _resolve_marker_data(tracked)
    if not marker:
        console.print(f"[red]Cannot load marker config for {tracked.id}[/red]")
        return

    state = _load_state(ctx)
    try:
        runner = get_agent_runner(marker)
        result = run_marker(
            repo_path=Path(tracked.repo_path),
            marker=marker,
            state=state,
            tracked=tracked,
            agent_runner=runner,
        )
        console.print(f"\n[bold green]Run complete:[/bold green] {result.marker_name}")
        console.print(f"  Experiments: {result.experiments}  Kept: {result.kept}  Discarded: {result.discarded}")
        if result.final_metric is not None:
            console.print(f"  Final metric: {result.final_metric}")
    except EngineError as e:
        console.print(f"[red]Engine error: {e}[/red]")


def _run_repo_markers(ctx: typer.Context, state, repo_name: str):
    """Run all active markers in a repo."""
    for tracked in state.markers:
        if tracked.repo_name != repo_name:
            continue
        _mf, _, eff = _resolve_marker_data(tracked)
        if eff == MarkerStatus.ACTIVE:
            console.print(f"\n[bold]Running {tracked.id}...[/bold]")
            _run_single_marker(ctx, tracked)


# ---------------------------------------------------------------------------
# Marker submenu
# ---------------------------------------------------------------------------

def _build_marker_detail_panel(tracked, marker, eff) -> list[str]:
    """Build info lines for the marker detail panel."""
    status_label = eff.value if eff else "unknown"
    info_lines = [f"Status: {status_label}"]
    if tracked.baseline is not None:
        info_lines.append(f"Baseline: {tracked.baseline}")
    if tracked.current is not None:
        info_lines.append(f"Current: {tracked.current}")
    if marker and marker.metric.target is not None:
        info_lines.append(f"Target: {marker.metric.target}")
    if marker:
        info_lines.append(f"Direction: {marker.metric.direction.value}")
    if tracked.branch:
        info_lines.append(f"Branch: {tracked.branch}")
    return info_lines


def _dispatch_submenu_action(ctx: typer.Context, tracked, marker, eff, action: str) -> bool:
    """Handle a marker submenu action. Returns False to go back, True to continue."""
    if action == "q":
        return False
    if action == "r":
        _run_single_marker(ctx, tracked)
    elif action == "s":
        _show_status_interactive(tracked, marker, eff)
    elif action == "t":
        _show_results_interactive(tracked)
    elif action == "k":
        _toggle_skip(ctx, tracked, marker)
    elif action == "p":
        _toggle_pause(ctx, tracked, marker)
    elif action == "e":
        _edit_config(tracked)
    elif action == "b":
        _show_branch(tracked)
    elif action == "i":
        _show_ideas_interactive(tracked)
    elif action == "c":
        _show_confidence_interactive(tracked)
    elif action == "f":
        _finalize_interactive(ctx, tracked)
    elif action == "m":
        _merge_interactive(ctx, tracked)
    return True


def _marker_submenu(ctx: typer.Context, tracked):
    """Interactive submenu for a selected marker."""
    from rich.panel import Panel
    from rich.prompt import Prompt

    while True:
        _mf, marker, eff = _resolve_marker_data(tracked)
        info_lines = _build_marker_detail_panel(tracked, marker, eff)
        console.print(Panel("\n".join(info_lines), title=tracked.id, border_style="blue"))

        choices = ["r", "s", "t", "k", "p", "e", "b", "i", "c", "f", "m", "q"]
        prompt_text = "[r] Run  [s] Status  [t] Results  [k] Skip  [p] Pause  [e] Edit  [b] Branch  [i] Ideas  [c] Confidence  [f] Finalize  [m] Merge  [q] Back"
        action = Prompt.ask(prompt_text, choices=choices)
        if not _dispatch_submenu_action(ctx, tracked, marker, eff, action):
            break


def _show_status_interactive(tracked, marker, eff):
    data = _format_tracked_json(tracked, marker, eff)
    for k, v in data.items():
        console.print(f"  [bold]{k}:[/bold] {v}")


def _show_results_interactive(tracked):
    from autoresearch.results import read_results

    repo_path = Path(tracked.repo_path)
    results = read_results(repo_path, tracked.marker_name)
    if not results:
        console.print("[dim]No results yet.[/dim]")
        return

    table = Table(title="Results")
    table.add_column("Commit")
    table.add_column("Metric", justify="right")
    table.add_column("Guard")
    table.add_column("Status")
    table.add_column("Confidence", justify="right")
    table.add_column("Description")

    for r in results:
        table.add_row(
            r.commit, str(r.metric), r.guard, r.status,
            str(r.confidence) if r.confidence else "--", r.description,
        )
    console.print(table)


def _toggle_skip(ctx: typer.Context, tracked, marker):
    from autoresearch.marker import MarkerStatus as MS

    state = _load_state(ctx)
    t = get_tracked(state, tracked.id)
    if not t:
        return
    if t.status_override == MS.SKIP:
        t.status_override = None
        console.print(f"[green]Unskipped {tracked.id}[/green]")
    else:
        t.status_override = MS.SKIP
        console.print(f"[yellow]Skipped {tracked.id}[/yellow]")
    save_state(state)


def _toggle_pause(ctx: typer.Context, tracked, marker):
    from autoresearch.marker import MarkerStatus as MS

    state = _load_state(ctx)
    t = get_tracked(state, tracked.id)
    if not t:
        return
    if t.status_override == MS.PAUSED:
        t.status_override = None
        console.print(f"[green]Resumed {tracked.id}[/green]")
    else:
        t.status_override = MS.PAUSED
        console.print(f"[yellow]Paused {tracked.id}[/yellow]")
    save_state(state)


def _edit_config(tracked):
    import os
    import shlex
    import subprocess

    editor = os.environ.get("EDITOR", "vi")
    mf_path = find_marker_file(Path(tracked.repo_path))
    if mf_path:
        subprocess.run([*shlex.split(editor), str(mf_path)])
    else:
        console.print(f"[red]Marker file not found in {tracked.repo_path}[/red]")


def _show_branch(tracked):
    import subprocess

    if not tracked.branch:
        console.print("[dim]No branch assigned yet.[/dim]")
        return
    console.print(f"[bold]Branch:[/bold] {tracked.branch}")
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-10", tracked.branch],
            cwd=tracked.repo_path,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout:
            console.print(result.stdout.rstrip())
        else:
            console.print("[dim]Branch not found in git log.[/dim]")
    except Exception:
        console.print("[dim]Could not read branch log.[/dim]")


def _show_ideas_interactive(tracked):
    from autoresearch.ideas import read_ideas

    content = read_ideas(Path(tracked.repo_path), tracked.marker_name)
    if content.strip():
        console.print(content)
    else:
        console.print("[dim]No ideas logged yet.[/dim]")


def _show_confidence_interactive(tracked):
    from autoresearch.metrics import compute_confidence, confidence_label
    from autoresearch.results import get_kept_metrics, read_results

    results = read_results(Path(tracked.repo_path), tracked.marker_name)
    kept = get_kept_metrics(results)
    if tracked.baseline is not None and tracked.current is not None:
        score = compute_confidence(kept, tracked.baseline, tracked.current)
        label = confidence_label(score)
        console.print(f"[bold]Confidence:[/bold] {label} ({score})" if score else "[dim]Not enough data.[/dim]")
    else:
        console.print("[dim]Baseline/current not set.[/dim]")


def _finalize_interactive(ctx: typer.Context, tracked):
    from autoresearch.finalize import finalize_marker
    from autoresearch.results import read_results

    results = read_results(Path(tracked.repo_path), tracked.marker_name)
    if not results:
        console.print("[dim]No results to finalize.[/dim]")
        return

    branches = finalize_marker(
        Path(tracked.repo_path), tracked.marker_name, results, tracked.branch
    )
    if not branches:
        console.print("[dim]No kept experiments to finalize.[/dim]")
        return

    console.print(f"[green]Created {len(branches)} finalization branch(es):[/green]")
    for b in branches:
        console.print(f"  {b['branch']} — {b['description']}")


def _merge_interactive(ctx: typer.Context, tracked):
    from rich.prompt import Prompt

    if not tracked.branch:
        console.print("[dim]No branch to merge.[/dim]")
        return

    target = Prompt.ask("Merge into", default="main")
    from autoresearch.finalize import merge_finalized

    try:
        commit = merge_finalized(Path(tracked.repo_path), tracked.branch, target)
        console.print(f"[green]Merged {tracked.branch} into {target} ({commit[:7]})[/green]")
    except Exception as e:
        console.print(f"[red]Merge failed: {e}[/red]")


# ---------------------------------------------------------------------------
# Daemon subcommands
# ---------------------------------------------------------------------------


@daemon_app.command("start")
def daemon_start(ctx: typer.Context):
    """Start the daemon in the background."""
    _init_ctx(ctx)
    from autoresearch.daemon import (
        check_stale_pid,
        daemonize,
        is_pid_alive,
        read_pid,
    )

    check_stale_pid()
    existing_pid = read_pid()
    if existing_pid and is_pid_alive(existing_pid):
        if is_headless(ctx):
            headless_output(ctx, err_json(f"Daemon already running (PID {existing_pid})"))
            raise typer.Exit(code=1)
        console.print(f"[red]Daemon already running (PID {existing_pid})[/red]")
        raise typer.Exit(code=1)

    try:
        config_path = ctx.obj.get("config_path")
        config = None
        if config_path:
            from autoresearch.config import load_config
            config = load_config(config_path)
        child_pid = daemonize(config=config)
        if is_headless(ctx):
            headless_output(ctx, ok_json({"pid": child_pid, "action": "started"}))
        else:
            console.print(f"[green]Daemon started (PID {child_pid})[/green]")
    except RuntimeError as e:
        if is_headless(ctx):
            headless_output(ctx, err_json(str(e)))
            raise typer.Exit(code=1)
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)


@daemon_app.command("stop")
def daemon_stop(ctx: typer.Context):
    """Stop the running daemon."""
    _init_ctx(ctx)
    from autoresearch.daemon import stop_daemon

    stopped = stop_daemon()
    if is_headless(ctx):
        if stopped:
            headless_output(ctx, ok_json({"action": "stopped"}))
        else:
            headless_output(ctx, err_json("No daemon running"))
            raise typer.Exit(code=1)
    else:
        if stopped:
            console.print("[green]Daemon stopped[/green]")
        else:
            console.print("[yellow]No daemon running[/yellow]")


def _compute_next_fire(cron_expr: str, last_run: Optional[str]) -> Optional[str]:
    """Compute the next scheduled fire time from a cron expression and last run timestamp."""
    from croniter import croniter
    from datetime import datetime, timezone

    if not last_run:
        return None
    try:
        last_dt = datetime.fromisoformat(last_run)
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        return croniter(cron_expr, last_dt).get_next(datetime).isoformat()
    except (ValueError, KeyError):
        return None


def _collect_scheduled_markers(state) -> list[dict]:
    """Build the list of scheduled marker dicts from tracked state."""
    from autoresearch.daemon import _resolve_cron_expression

    scheduled = []
    for tracked in state.markers:
        _mf, marker, _ = _resolve_marker_data(tracked)
        if not marker:
            continue
        cron_expr = _resolve_cron_expression(marker.schedule)
        if cron_expr:
            scheduled.append({
                "marker": tracked.id,
                "schedule_type": marker.schedule.type,
                "cron": cron_expr,
                "next_run": _compute_next_fire(cron_expr, tracked.last_run),
                "last_run": tracked.last_run,
            })
    return scheduled


def _print_daemon_status(running: bool, pid, state, scheduled: list[dict]) -> None:
    """Render daemon status to console."""
    status_text = "[green]running[/green]" if running else "[dim]stopped[/dim]"
    console.print(f"Daemon: {status_text}" + (f" (PID {pid})" if pid else ""))
    if state.daemon.started_at:
        console.print(f"Started: {state.daemon.started_at}")
    if scheduled:
        table = Table(title="Scheduled Markers")
        table.add_column("Marker")
        table.add_column("Schedule")
        table.add_column("Next Run")
        table.add_column("Last Run")
        for s in scheduled:
            table.add_row(s["marker"], s["cron"], s["next_run"] or "--", s["last_run"] or "--")
        console.print(table)
    else:
        console.print("[dim]No scheduled markers.[/dim]")


@daemon_app.command("status")
def daemon_status(ctx: typer.Context):
    """Show daemon status and scheduled markers."""
    _init_ctx(ctx)
    from autoresearch.daemon import (
        check_stale_pid,
        is_pid_alive,
        read_pid,
    )

    check_stale_pid()
    pid = read_pid()
    running = pid is not None and is_pid_alive(pid)
    state = _load_state(ctx)
    scheduled = _collect_scheduled_markers(state)

    data = {
        "running": running,
        "pid": pid,
        "started_at": state.daemon.started_at,
        "scheduled_markers": scheduled,
    }

    if is_headless(ctx):
        headless_output(ctx, ok_json(data))
    else:
        _print_daemon_status(running, pid, state, scheduled)


@daemon_app.command("logs")
def daemon_logs(
    ctx: typer.Context,
    lines: int = typer.Option(50, "--lines", "-n", help="Number of lines to show"),
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow log output"),
):
    """Show daemon log output."""
    _init_ctx(ctx)
    from autoresearch.daemon import LOG_PATH

    if not LOG_PATH.is_file():
        if is_headless(ctx):
            headless_output(ctx, err_json("No log file found"))
            raise typer.Exit(code=1)
        console.print("[dim]No log file found.[/dim]")
        raise typer.Exit(code=1)

    if follow:
        if is_headless(ctx):
            headless_output(ctx, err_json("--follow is not supported in headless mode"))
            raise typer.Exit(code=2)
        import subprocess
        subprocess.run(["tail", "-f", "-n", str(lines), str(LOG_PATH)])
    else:
        content = LOG_PATH.read_text()
        log_lines = content.splitlines()[-lines:]
        if is_headless(ctx):
            headless_output(ctx, ok_json({"lines": log_lines}))
        else:
            for line in log_lines:
                console.print(line)
