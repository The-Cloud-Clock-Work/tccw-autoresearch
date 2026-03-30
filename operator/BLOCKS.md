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

## Block 3: CLI — Interactive + Headless ▸ `ready`

The interface. Dual-mode CLI following `/enhance-cli` pattern. Every command works interactively AND with `--headless`.

**Scope:**
- [ ] Root command group with `--headless` global flag
- [ ] Home directory view: list all tracked markers, numbered selection, action keys
- [ ] Repo directory view: auto-detect `.autoresearch.yaml`, prompt to register
- [ ] Marker submenu: run, status, results, skip/unskip, pause/resume, ideas, confidence, finalize, merge
- [ ] `autoresearch run -m <marker>` — invoke engine for single marker
- [ ] `autoresearch run --repo <name>` — run all active markers in a repo
- [ ] `autoresearch add` / `detach` / `skip` / `status` / `results` / `ideas` / `confidence`
- [ ] `autoresearch finalize <marker>` — cherry-pick + squash winning commits into clean branches
- [ ] `autoresearch merge <marker>` — merge finalized branch
- [ ] Headless equivalents: JSON output for every command, all inputs via flags
- [ ] Helper functions: headless_confirm, headless_prompt, headless_output
- [ ] Rich tables for interactive display

**Outputs:** `src/autoresearch/cli.py`, `utils.py`
**Depends on:** Block 1 (marker/state/results models), Block 2 (engine invocation)
**SPECS reference:** Sections 2.1-2.7 (CLI), 4.12 (finalization)

---

## Block 4: Daemon + Packaging ▸ `ready`

The runtime. Long-running daemon for scheduled execution, plus pip-installable packaging for remote environments.

**Scope:**
- [ ] `autoresearch daemon start/stop/status/logs` commands
- [ ] Schedule evaluation: read marker schedules, fire when due
- [ ] PID file management: `~/.autoresearch/daemon.pid`
- [ ] Log management: `~/.autoresearch/daemon.log`
- [ ] Max concurrent markers limit
- [ ] Crash recovery: detect stale PID, auto-restart
- [ ] `pip install tccw-autoresearch` packaging (PyPI or private index)
- [ ] Entry point: `autoresearch` CLI binary via pyproject.toml `[project.scripts]`
- [ ] `.autoresearch.yaml` dogfood: markers for this repo's own self-improvement
- [ ] End-to-end verification: fresh install → add marker → run → results

**Outputs:** `src/autoresearch/daemon.py`, packaging config, dogfood marker
**Depends on:** Block 1 (state/config), Block 2 (engine), Block 3 (CLI commands)
**SPECS reference:** Sections 3 (daemon), 9 (execution environments)
