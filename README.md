# tccw-autoresearch

**Agnostic autonomous improvement engine.** Point it at any codebase — it makes it measurably better overnight while you sleep.

Inspired by [karpathy/autoresearch](https://github.com/karpathy/autoresearch) — methodology only, zero code dependency. Clean-room implementation of the loop pattern, stripped of all ML assumptions.

---

## What It Does

```
LOOP:
  1. Edit target files
  2. Run immutable harness
  3. Measure single metric
  4. If improved → keep (git commit)
  5. If worse  → discard (git reset)
  6. REPEAT until budget exhausted
```

Works on anything with a measurable outcome: test pass rates, build times, response latency, error counts, coverage percentages. No GPU. No ML. Tests replace training runs.

---

## Hard Dependency: Claude Code

AutoResearch does **not** edit code itself. It is an orchestrator. The actual code changes are made by [Claude Code](https://docs.anthropic.com/en/docs/claude-code) agents — Anthropic's CLI for autonomous coding.

**You must have `claude` installed and on your PATH.** The engine spawns `claude` as a subprocess for each experiment, passing it the marker's mutable/immutable file rules, the agent profile, and permission flags. Claude Code reads the code, forms hypotheses, makes edits, and runs the harness. AutoResearch decides whether to keep or discard the result.

```
autoresearch (orchestrator)
  └── claude (agent) ← does the actual coding
        ├── reads mutable files
        ├── edits code
        ├── runs metric harness
        └── commits if improved
```

Install Claude Code: https://docs.anthropic.com/en/docs/claude-code

```bash
# Verify it's available
claude --version
```

Without `claude` on PATH, `autoresearch run` will fail.

---

## The Marker

A `.autoresearch/config.yaml` in any repository declares what to improve:

```yaml
markers:
  - name: test-suite-health
    description: "Improve test coverage and reduce test runtime"
    status: active
    target:
      mutable:
        - tests/test_daemon.py
        - tests/test_engine.py
      immutable:
        - src/autoresearch/daemon.py
        - src/autoresearch/engine.py
    metric:
      command: "python3 -m pytest --tb=no -q 2>&1 | tail -1"
      extract: "grep -oP '\\d+(?= passed)'"
      direction: higher
      baseline: 2541
    guard:
      command: "python3 -m pytest --tb=short -q 2>&1"
      extract: "grep -oP '\\d+(?= passed)'"
      threshold: 2541
      rework_attempts: 2
    loop:
      model: sonnet
      budget_per_experiment: 25m
      max_experiments: 10
    agent:
      name: copilot
      model: sonnet
      permission_mode: bypassPermissions
      allowed_tools:
        - "Edit(tests/*)"
        - "Bash(python3 *)"
        - "Bash(pytest *)"
      disallowed_tools:
        - "Bash(rm *)"
        - "Bash(git push *)"
        - "Bash(curl *)"
```

Add the file, run `autoresearch` — the engine handles the rest.

---

## Usage

```bash
# Interactive TUI (select marker, press 'r' to run)
autoresearch

# Headless — for AI agents, CI/CD, cron
autoresearch run -m test-suite-health --headless

# Initialize .autoresearch/ in a repo with default agent profile
autoresearch init

# Status, results, confidence
autoresearch status -m tccw-autoresearch:test-suite-health --headless
autoresearch results -m tccw-autoresearch:test-suite-health --headless
autoresearch confidence -m tccw-autoresearch:test-suite-health --headless

# Finalize: clean branches from messy experiment history
autoresearch finalize -m tccw-autoresearch:test-suite-health --headless

# Daemon — scheduled overnight runs
autoresearch daemon start
autoresearch daemon status
autoresearch daemon stop
```

---

## Intelligence Features

| Feature | Description |
|---------|-------------|
| **Ideas backlog** | Failed experiments log *why* they were interesting — future sessions don't repeat mistakes |
| **Graduated escalation** | 3 failures → REFINE → 5 → PIVOT → 2 PIVOTs → SEARCH → 3 PIVOTs → HALT |
| **Statistical confidence** | MAD-based scoring after 3+ experiments — ignores benchmark noise |
| **Dual-gate guard** | Metric gate + regression guard — prevents gaming the metric by breaking something else |
| **Finalization** | Clean, reviewable branches from messy experimental history |
| **Agent profiles** | Per-marker Claude Code settings.json + CLAUDE.md generated at runtime |
| **Permission enforcement** | Mutable/immutable translated to `--allowedTools`/`--disallowedTools` CLI flags |
| **Telemetry** | Stream-json parsing into TelemetryReport (tokens, cost, tools, errors) |

---

## Quick Start — Set Up Any Repo in 3 Steps

### 1. Install the CLI

**Prerequisites:**
- Python 3.10+
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (`claude` CLI) installed and authenticated — this is what actually edits code

```bash
# Install autoresearch
git clone git@github.com:The-Cloud-Clock-Work/tccw-autoresearch.git
cd tccw-autoresearch
pip install -e .

# Verify both are available
autoresearch --help
claude --version
```

### 2. Initialize your target repo

```bash
cd /path/to/your-project
autoresearch init
```

This creates `.autoresearch/config.yaml` with a starter marker and `.autoresearch/agents/` with the default agent profile.

### 3. Configure your marker

Edit `.autoresearch/config.yaml` to match your project:

```yaml
markers:
  - name: my-improvement          # Pick a short, descriptive name
    description: "What you want to improve"
    status: active                 # Set to 'active' to run

    target:
      mutable:                     # Files the engine CAN edit
        - src/**/*.py
      immutable:                   # Test/harness files — NEVER touched
        - tests/test_main.py

    metric:
      command: "pytest tests/test_main.py -q --tb=no 2>&1 | tail -1"
      extract: "grep -oP '\\d+(?= passed)'"
      direction: higher            # 'higher' = more is better, 'lower' = less is better
      baseline: 10                 # Current value before any improvement

    loop:
      model: sonnet                # AI model: sonnet, opus, haiku
      budget_per_experiment: 10m   # Time limit per experiment
      max_experiments: 20          # Stop after N experiments
```

**Key rules for the marker:**
- `metric.command` must be a **shell command** that produces output (not a bare regex)
- `metric.extract` must be a **shell command** that filters the output to a single number
- `target.immutable` files are protected — the agent cannot edit them
- `target.mutable` files are the only ones the agent is allowed to change

### Run it

```bash
# Interactive — pick marker from TUI menu
autoresearch

# Headless — for AI agents, CI/CD, cron, scripts
autoresearch run -m my-improvement --headless

# Check progress
autoresearch status --headless
autoresearch results -m my-improvement --headless
```

### Common marker examples

**Increase test pass count:**
```yaml
metric:
  command: "pytest tests/ -q --tb=no 2>&1 | tail -1"
  extract: "grep -oP '\\d+(?= passed)'"
  direction: higher
  baseline: 42
```

**Reduce build time (seconds):**
```yaml
metric:
  command: "bash -c 'TIMEFORMAT=%R; time make build 2>&1'"
  extract: "tail -1"
  direction: lower
  baseline: 120
```

**Increase code coverage (%):**
```yaml
metric:
  command: "pytest --cov=src --cov-report=term 2>&1 | tail -1"
  extract: "grep -oP '\\d+(?=%)'"
  direction: higher
  baseline: 65
```

**Reduce lint warnings:**
```yaml
metric:
  command: "ruff check src/ 2>&1 | tail -1"
  extract: "grep -oP '\\d+(?= error)'"
  direction: lower
  baseline: 30
```

---

## Architecture

```
src/autoresearch/
  marker.py          # .autoresearch/config.yaml schema + parser (Pydantic)
  engine.py          # Core experiment loop + AgentRunner ABC
  worktree.py        # Git worktree isolation per marker
  metrics.py         # Harness execution + metric extraction + MAD confidence
  program.py         # Runtime program.md generation (string.Template)
  agent_profile.py   # settings.json + CLAUDE.md generation + permission flags
  telemetry.py       # Stream-json telemetry parsing
  finalize.py        # Cherry-pick + squash winning commits
  cli.py             # CLI entry point (Typer, 13 commands, dual-mode)
  cli_utils.py       # Headless helpers (JSON output, prompts)
  daemon.py          # Daemon service (cron, double-fork, concurrent runs)
  state.py           # Global state (~/.autoresearch/state.json)
  config.py          # Config defaults (~/.autoresearch/config.yaml)
  results.py         # results.tsv read/write
  ideas.py           # ideas.md backlog
  utils.py           # Shared utilities (parse_duration)
  agents/default/    # Default agent profile (CLAUDE.md, settings, rules)
```

**Design principles:**
- **Agnostic** — no assumptions about what it improves
- **Self-contained** — repo + marker file = everything needed to run
- **Dual-mode** — every command works interactively AND headlessly (`--headless`)
- **Permission-locked** — agent can only edit mutable files, enforced via CLI flags
- **No ML dependencies** — no torch, no CUDA, no GPU

---

## Status

All blocks complete. 2,557 tests passing. CI gates PRs via `.github/workflows/ci.yml`.

| Block | Description | Status |
|-------|-------------|--------|
| Block 1 | Foundation — marker schema, state, results, ideas | Done |
| Block 2 | Engine — loop, worktree, metrics, escalation, confidence | Done |
| Block 3 | CLI — interactive TUI + headless JSON, 13 commands | Done |
| Block 4 | Daemon + packaging — cron, double-fork, pip install | Done |
| Block 5 | Agent profiles + telemetry — permissions, stream-json | Done |

---

## Dependencies

- `pydantic>=2.0` — schema validation
- `pyyaml>=6.0` — YAML parsing
- `rich>=13.0` — TUI rendering
- `typer>=0.12` — CLI framework
- `croniter>=2.0` — cron schedule evaluation

---

## License

MIT
