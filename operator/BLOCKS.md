# BLOCKS.md — Active Work Blocks

> **Purpose:** Four modular blocks that build everything end-to-end. Each block is a plan — the operator works on one block at a time, potentially in worktrees or parallel agent dispatches.
> **Rule:** Update this file every session. Blocks move through: `design` → `ready` → `in-progress` → `done`
> **Methodology:** Each block becomes its own plan. Agent reads VISION → SPECS → BLOCKS → starts work on the assigned block. Progress saved here after each session.

---

## Block 1: Foundation — Marker Schema + State + Results ▸ `done`

The data layer. Everything else depends on this. Defines how markers are parsed, how state is tracked, and how results are stored.

**Scope:**
- [x] Pydantic models for `.autoresearch.yaml` schema (marker, target, metric, guard, escalation, schedule, results)
- [x] YAML parser: read `.autoresearch.yaml`, validate, return typed objects
- [x] Global state management: `~/.autoresearch/state.json` read/write, config.yaml defaults
- [x] Results management: `.autoresearch/<marker>/results.tsv` create, append, read
- [x] Ideas backlog: `.autoresearch/<marker>/ideas.md` create, append, read
- [x] Marker ID resolution: `repo_name:marker_name` with conflict handling
- [x] State override logic: local state.json overrides YAML status
- [x] `pyproject.toml` with package definition, dependencies, entry point

**Completed:** 2026-03-30 — 38 tests passing, all modules importable, `pip install -e .` works
**Outputs:** `src/autoresearch/marker.py`, `config.py`, `state.py`, `results.py`, `ideas.py`, `pyproject.toml`
**Depends on:** Nothing — this is the base
**SPECS reference:** Sections 1 (marker schema), 5 (results), 6 (global state)

---

## Block 2: Engine — The Loop + Git Isolation ▸ `done`

The core. The edit→test→measure→keep/discard loop with git worktree isolation, all the intelligence features (guard, escalation, confidence, ideas), and program.md generation.

**Scope:**
- [x] Git worktree create/cleanup per marker (`autoresearch/<marker>-<date>` branches)
- [x] Program.md template generation from marker config (ephemeral, at runtime)
- [x] Core experiment loop: invoke agent → run harness → extract metric → keep/discard
- [x] Guard command (dual-gate): metric gate + regression gate, rework attempts
- [x] Graduated failure escalation: REFINE(3) → PIVOT(5) → SEARCH(2) → HALT(3)
- [x] Statistical confidence scoring: MAD-based after 3+ kept experiments
- [x] Ideas backlog writes: agent logs discarded-but-promising, near-misses, external research
- [x] Crash handling: fix-and-retry vs discard, consecutive crash detection
- [x] Agent invocation interface (pluggable — Claude Code `-p` as first implementation)

**Completed:** 2026-03-30 — 105 new tests (143 total), all modules importable
**Outputs:** `src/autoresearch/engine.py`, `worktree.py`, `metrics.py`, `program.py`
**Depends on:** Block 1 (reads marker config, writes results/state)
**SPECS reference:** Sections 4.1-4.13 (engine), 4.8-4.12 (intelligence features)

**Design decisions:**
- Git operations via subprocess (no gitpython dependency)
- Agent invocation via ABC (`AgentRunner`) — `ClaudeCodeRunner` is first implementation
- Escalation state is in-memory per run, not persisted (cross-run memory via results.tsv + ideas.md)
- Program.md generated via `string.Template` (safe with `{braces}` in shell commands)

### Sweep — 2026-03-30
- **Issues found:** 21 (quality: 21, compliance: n/a — agent rate-limited, integration: n/a — agent rate-limited)
- **Fixed:** 10
  - CRITICAL: `str.format()` crash on `{` in shell commands → switched to `string.Template`
  - CRITICAL: `UnicodeEncodeError` on binary harness output → `errors="replace"` + timeout partial output preserved
  - HIGH: falsy `0.0` metric dropped by `or` fallback → explicit `is not None` check
  - HIGH: worktree leak on unhandled exception → `try/finally` around main loop
  - HIGH: `status_override` set as string instead of enum → `MarkerStatus.NEEDS_HUMAN` directly
  - HIGH: silent `GitError` swallow on reset → `logger.warning`
  - MEDIUM: hardcoded 5m rework budget → uses `marker.loop.budget_per_experiment`
  - MEDIUM: bare `subprocess.run` in `git_commit` → uses `_run_git` for consistent error handling
  - MEDIUM: inline `datetime` import → moved to module top
  - MEDIUM: temp dir leak on worktree creation failure → cleanup in except block
- **Remaining:** 11 low-severity items (shell injection by design — marker files are operator-authored, regex edge case for `-.5`, dead exception type in except tuple, zombie process cleanup, description extraction heuristic, test gaps for rework call counting)

---

## Block 3: CLI — Interactive + Headless ▸ `done`

The interface. Dual-mode CLI following `/enhance-cli` pattern. Every command works interactively AND with `--headless`.

**Scope:**
- [x] Root command group with `--headless` global flag
- [x] Home directory view: list all tracked markers, numbered selection, action keys
- [x] Repo directory view: auto-detect `.autoresearch.yaml`, prompt to register
- [x] Marker submenu: run, status, results, skip/unskip, pause/resume, ideas, confidence, finalize, merge
- [x] `autoresearch run -m <marker>` — invoke engine for single marker
- [x] `autoresearch run --repo <name>` — run all active markers in a repo
- [x] `autoresearch add` / `detach` / `skip` / `status` / `results` / `ideas` / `confidence`
- [x] `autoresearch finalize <marker>` — cherry-pick + squash winning commits into clean branches
- [x] `autoresearch merge <marker>` — merge finalized branch
- [x] Headless equivalents: JSON output for every command, all inputs via flags
- [x] Helper functions: headless_confirm, headless_prompt, headless_output
- [x] Rich tables for interactive display

**Completed:** 2026-03-30 — 49 new tests (192 total), all commands dual-mode
**Outputs:** `src/autoresearch/cli.py`, `cli_utils.py`, `finalize.py`
**Depends on:** Block 1 (marker/state/results models), Block 2 (engine invocation)
**SPECS reference:** Sections 2.1-2.7 (CLI), 4.12 (finalization)

**Design decisions:**
- CLI framework: Typer (entry point `cli:app` matches `typer.Typer()` naturally)
- Interactive input: `rich.prompt.Prompt.ask()` with character choices (portable, testable)
- TUI rendering: `rich.table.Table` for marker lists, `rich.panel.Panel` for submenu detail
- Finalization: separate `finalize.py` module (reusable by daemon in Block 4)
- JSON convention: `{"status": "ok"/"error", "data": ...}` with exit codes 0/1/2

### Sweep — 2026-03-30
- **Issues found:** 16 (quality: 10, compliance: 3, integration: 3)
- **Fixed:** 10
  - CRITICAL: cherry-pick loop continues after failure in finalize.py → added `continue` + applied commit tracking
  - HIGH: duplicated `_run_git` in finalize.py → import from worktree.py
  - HIGH: `defaultdict` defeated by `.get()` in finalize.py → simplified to `dict.setdefault`
  - HIGH: hardcoded `main` in merge-base → accept `target_branch` parameter
  - HIGH: `$EDITOR` with spaces crashes subprocess → use `shlex.split`
  - MEDIUM: missing headless `pause` command → added `@app.command("pause")`
  - MEDIUM: error JSON goes to stdout not stderr → route errors to stderr in `headless_output`
  - MEDIUM: dead `load_config` import in cli.py → removed
  - MEDIUM: dead `state_path`/`config_path` code in `_load_state` → cleaned up
  - MEDIUM: branch cleanup on failure uses `checkout -` not `source_branch` → fixed
- **Remaining:** 6 low-severity items (test assertion gaps for error JSON structure, `metric_delta` semantics, double-prompt in repo mode UX)

---

## Block 4: Daemon + Packaging ▸ `done`

The runtime. Long-running daemon for scheduled execution, plus pip-installable packaging for remote environments.

**Scope:**
- [x] `autoresearch daemon start/stop/status/logs` commands
- [x] Schedule evaluation: read marker schedules, fire when due
- [x] PID file management: `~/.autoresearch/daemon.pid`
- [x] Log management: `~/.autoresearch/daemon.log`
- [x] Max concurrent markers limit
- [x] Crash recovery: detect stale PID (auto-restart deferred per SPECS 3.4)
- [x] `pip install tccw-autoresearch` packaging (PyPI or private index)
- [x] Entry point: `autoresearch` CLI binary via pyproject.toml `[project.scripts]`
- [x] `.autoresearch.yaml` dogfood: markers for this repo's own self-improvement
- [x] End-to-end verification: fresh install → add marker → run → results

**Completed:** 2026-03-30 — 50 new tests (245 total), daemon + packaging ready
**Outputs:** `src/autoresearch/daemon.py`, `utils.py`, `.autoresearch.yaml`, packaging config
**Depends on:** Block 1 (state/config), Block 2 (engine), Block 3 (CLI commands)
**SPECS reference:** Sections 3 (daemon), 9 (execution environments)

**Design decisions:**
### Sweep — 2026-03-30
- **Issues found:** 18 (quality: 13, compliance: 3, integration: 6 — with deduplication: 14 unique)
- **Fixed:** 10
  - CRITICAL: `daemonize()` returned first-child PID (dead) instead of grandchild → pipe-based PID relay
  - HIGH: `stop_daemon()` returned True even if process never terminated → return False on timeout
  - HIGH: `is_pid_alive` returned False for `PermissionError` (alive process, different user) → return True
  - HIGH: `daemonize()` didn't redirect stdin to `/dev/null` → added `os.dup2(devnull, stdin)`
  - HIGH: `daemon_start` ignored `--config` flag → forward config to `daemonize()`
  - MEDIUM: `logging.basicConfig` without `force=True` in daemon → added `force=True`
  - MEDIUM: `parse_duration` regex not anchored, dead alternation order → `re.fullmatch` + longest-first
  - MEDIUM: Stale PID didn't reset `state.daemon.running` → reset state in `stop_daemon`
  - MEDIUM: `daemonize()` didn't `waitpid` first child (zombie) → added `os.waitpid`
  - LOW: Dead `field` import in engine.py → removed
- **Remaining:** 4 low-severity items (test coverage for timeout zombie scenario, daemon_logs --follow silently ignored in headless, license TOML format, end-to-end integration test script)

**Design decisions:**
- Cron evaluation via `croniter` (zero-dep, battle-tested)
- Schedule types map to cron internally: overnight=`0 1 * * *`, weekend=`0 1 * * 6`, on-demand=never
- Unix double-fork daemonization (no extra dependency)
- `threading.Thread` + `Semaphore(max_concurrent)` for concurrent runs
- `parse_duration()` extracted to shared `utils.py` (reused by engine + daemon)
- State reloaded from disk each tick (CLI changes picked up automatically)

---

## Block 5: Agent Profiles + Telemetry ▸ `done`

Hard permission enforcement via Claude Code's permission system, telemetry capture for feedback loops, and full agent project structure.

**Scope:**
- [x] `AgentConfig` model on `Marker` (name, model, effort, permission_mode, allowed/disallowed tools, extra_flags)
- [x] `agent_profile.py` — generate `settings.json` + `CLAUDE.md` per marker at runtime
- [x] `telemetry.py` — parse `--output-format stream-json` into `TelemetryReport` (tokens, cost, tools, errors)
- [x] `ClaudeCodeRunner` rewrite — `--permission-mode bypassPermissions`, `--settings`, `--append-system-prompt-file`, `--allowedTools`/`--disallowedTools`
- [x] Default agent as full Claude Code project: `.claude/` with settings, rules, commands, agents, skills
- [x] `.env.example` + `.env` loading before agent subprocess
- [x] `--append-system-prompt-file` for default CLAUDE.md injection into all agent runs
- [x] `autoresearch init` — scaffold `.autoresearch/` with template config + default agent (additive, non-destructive)
- [x] `init_autoresearch_dir()` resolves via `__file__` for both dev and pip installs
- [x] Error feedback: telemetry errors/denials written to ideas.md
- [x] Tests for agent_profile, telemetry modules

**Completed:** 2026-03-31 — 281 tests across 17 files
**Outputs:** `agent_profile.py`, `telemetry.py`, `src/autoresearch/agents/default/` (full project structure)
**Depends on:** Block 1 (marker schema), Block 2 (engine ABC), Block 4 (daemon caller)
**SPECS reference:** Section 4.13 (agent invocation — now designed and implemented)

**Design decisions:**
- `--permission-mode bypassPermissions` instead of `--dangerously-skip-permissions` (proper permission system)
- `settings.json` generated at runtime from marker's mutable/immutable lists → `permissions.allow`/`deny`
- Default agent dir at `src/autoresearch/agents/default/` — resolves via `Path(__file__).parent` for pip compatibility
- Stream-json telemetry parsed into `TelemetryReport` dataclass with 12 fields
- `.env` loaded via `dotenv` before subprocess, not passed as CLI flags (secrets stay out of process list)
- `--append-system-prompt-file` injects default CLAUDE.md into all agents (base rules, identity, error recovery)

---

## Block 6: Documentation + Onboarding Skill ▸ `done`

Documentation scaffold and `/onboard` skill for frictionless repo setup.

**Scope:**
- [x] `docs/` directory with 15 files + `00-INDEX.md` covering architecture, core domain, CLI, agents, config, development
- [x] README: Quick Start onboarding guide (install → init → configure → run)
- [x] README + docs: Claude Code documented as hard dependency (orchestrator/agent relationship)
- [x] `.claude/skills/onboard/` — interactive Q&A skill to set up autoresearch on any repo
- [x] Common metric templates (pytest, jest, go, rust, coverage, build time, lint)

**Completed:** 2026-04-01
**Outputs:** `docs/`, `.claude/skills/onboard/`, updated `README.md`
**Depends on:** Blocks 1–5 (documents existing implementation)

### Sweep — 2026-04-01
- **Issues found:** 13 (quality: 13, compliance: 4, integration: 1 — deduplicated)
- **Fixed:** 13
  - HIGH: `docs/2A-CLI.md` listed wrong commands (`track`/`untrack`/`set-status`) → corrected to actual CLI commands (`add`/`detach`/`skip`/`pause` + 8 missing commands)
  - HIGH: `docs/4B-TELEMETRY.md` fabricated TSV columns → corrected to actual schema (commit, metric, guard, status, confidence, description)
  - HIGH: `docs/0B-QUICKSTART.md` used legacy `.autoresearch.yaml` path → corrected to `.autoresearch/config.yaml`
  - HIGH: `docs/0A-ARCHITECTURE.md` diagram attributed commit/discard to agent → corrected to orchestrator
  - HIGH: `docs/1A-MARKER.md` claimed CWD-upward search → corrected (no upward traversal)
  - HIGH: `01_validate_repo.sh` `.git` directory check failed on worktrees → use `git rev-parse`
  - MEDIUM: `docs/1D-STATE.md` referenced `track`/`untrack` → corrected to `add`/`detach`
  - MEDIUM: `docs/1B-ENGINE.md` mislabeled idea/program steps → corrected to actual flow
  - MEDIUM: `docs/5A-TESTING.md` claimed "mock git repos" in fixtures → corrected to actual files
  - MEDIUM: `docs/3A-AGENTS.md` described copilot as fully implemented → marked as planned
  - MEDIUM: `operator/SPECS.md` section 1.1 still said `.autoresearch.yaml` at root → updated to canonical `.autoresearch/config.yaml`
  - LOW: `docs/0B-QUICKSTART.md` marker `-m` didn't show full ID format → added `repo:marker` format
  - LOW: BLOCKS.md not updated with session work → added Block 6
- **Remaining:** 0
