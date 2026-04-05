# The Cloud Clock Work - Autoresearch

**A Claude Code wrapper that makes any codebase measurably better overnight.**

```bash
pip install tccw-autoresearch
cd your-project
autoresearch init
```

Claude opens. It scans your project. Asks what you want to improve. Configures everything. Runs the first experiment. Done.

---

## What Is This?

AutoResearch is an orchestrator that sits on top of [Claude Code](https://docs.anthropic.com/en/docs/claude-code). It gives Claude a metric, a budget, and permission to edit specific files — then measures whether the code got better.

```
autoresearch (orchestrator)
  └── claude (the brain)
        ├── reads your code
        ├── forms a hypothesis
        ├── edits files
        ├── runs your metric
        └── commits if improved, reverts if not
```

**You define the metric. Claude does the work. AutoResearch decides what to keep.**

Reduce lint errors. Increase test coverage. Cut build times. Fix code smells. Anything you can measure with a shell command.

---

## Requirements

- **Python 3.10+**
- **[Claude Code](https://docs.anthropic.com/en/docs/claude-code)** installed and authenticated (`claude --version`)

That's it. No Docker. No GPU. No ML frameworks. No infrastructure.

---

## How It Works

### 1. Install

```bash
pip install tccw-autoresearch
```

### 2. Initialize (AI-guided)

```bash
cd your-project
autoresearch init
```

This spawns an interactive Claude Code session with the `/onboard` skill:
- Claude scans your project, detects the tech stack
- Asks what you want to improve (lint, coverage, build time, custom)
- Suggests the right metric command for your stack
- Asks which files are mutable (agent can edit) vs immutable (never touched)
- Writes `.autoresearch/config.yaml`
- Measures baseline
- Optionally runs the first experiment

Use `--no-claude` to skip the wizard and edit config manually.

### 3. Run

```bash
# Interactive TUI
autoresearch

# Headless (CI/CD, cron, scripts)
autoresearch run -m my-marker --headless

# Check progress
autoresearch status --headless
autoresearch results -m my-marker --headless
```

### 4. What Happens

```
LOOP (per experiment):
  1. Create git worktree (isolated branch)
  2. Spawn Claude Code agent with your rules
  3. Agent edits mutable files, guided by issues_command
  4. Run metric command → extract number
  5. If improved → keep (git commit)
  6. If worse → discard (git reset)
  7. Budget countdown warns agent when time is low
  8. REPEAT until budget exhausted or HALT
```

Every kept experiment is a commit. Auto-merge creates PRs with full audit trail.

---

## The Marker File

`.autoresearch/config.yaml` is the only config you need:

```yaml
markers:
  - name: lint-quality
    description: "Reduce lint errors"
    status: active
    target:
      mutable: ["src/**/*.py"]        # Agent CAN edit these
      immutable: ["tests/**/*.py"]    # Agent CANNOT touch these
    metric:
      command: "ruff check src/ 2>&1"
      extract: "grep -oP 'Found \\K\\d+'"
      direction: lower                # lower = better
      baseline: 163
      issues_command: "ruff check src/ --output-format concise | head -30"
    loop:
      model: sonnet
      budget_per_experiment: 20m
      max_experiments: 10
    auto_merge:
      enabled: true
      target_branch: dev
```

### Common Metrics

| Goal | `metric.command` | `metric.extract` | `direction` |
|------|-----------------|-------------------|-------------|
| Reduce lint errors | `ruff check src/ 2>&1` | `grep -oP 'Found \K\d+'` | lower |
| Increase test passes | `pytest tests/ -q --tb=no 2>&1 \| tail -1` | `grep -oP '\d+(?= passed)'` | higher |
| Increase coverage % | `pytest --cov=src --cov-report=term 2>&1 \| tail -1` | `grep -oP '\d+(?=%)'` | higher |
| Reduce build time | `bash -c 'TIMEFORMAT=%R; time make build 2>&1'` | `tail -1` | lower |
| Reduce ESLint errors | `npx eslint src/ 2>&1 \| tail -1` | `grep -oP '\d+(?= problem)'` | lower |

**Any shell command that outputs a number works.**

---

## Claude Code Integration

AutoResearch is built around Claude Code at every level:

| Feature | How Claude Code Is Used |
|---------|------------------------|
| **Experiments** | Each experiment spawns `claude` as a subprocess with `--permission-mode`, `--allowedTools`, `--disallowedTools` |
| **Agent profiles** | `.autoresearch/agents/default/CLAUDE.md` + `settings.json` — shipped with the package |
| **Budget countdown** | PostToolUse hook injects remaining time via `additionalContext` after every tool call |
| **`autoresearch init`** | Spawns interactive Claude Code session with `/onboard` skill |
| **`/autoresearch` skill** | When you open the project in Claude Code: run, status, logs |
| **`/onboard` skill** | Interactive wizard — scans project, configures marker, measures baseline |
| **Issues injection** | `issues_command` output injected into agent prompt — exact `file:line:rule` targets |
| **Telemetry** | Parses Claude Code `stream-json` output for tokens, cost, tools, errors |

### Custom Agent Profiles

The default agent ships with the package. Duplicate to customize:

```bash
cp -r .autoresearch/agents/default .autoresearch/agents/my-agent
# Edit my-agent/CLAUDE.md, settings.json, hooks/
# Update config.yaml: agent.name: my-agent
```

Custom agents inherit default hooks (budget countdown) via symlinks.

---

## Intelligence Features

| Feature | Description |
|---------|-------------|
| **Issues command** | Agent gets exact `file:line:rule` instead of exploring broadly |
| **Budget countdown** | 3 tiers: working → wrap up → COMMIT NOW |
| **Graduated escalation** | 3 fails → refine → 5 → pivot → search → halt |
| **Statistical confidence** | MAD-based scoring after 3+ experiments |
| **Dual-gate guard** | Metric + regression guard — prevents gaming |
| **Ideas backlog** | Failed experiments log why — future sessions don't repeat |
| **Auto-merge** | Every KEEP → PR → auto-merge to dev → promotion PR to main |
| **Always-commit** | Engine commits after agent exits regardless of timeout |

---

## CLI Reference

```bash
autoresearch init          # AI-guided setup (spawns Claude Code)
autoresearch               # Interactive TUI
autoresearch run           # Run experiments
autoresearch status        # Marker dashboard
autoresearch results       # Experiment history
autoresearch confidence    # Statistical confidence scores
autoresearch ideas         # Ideas backlog
autoresearch add           # Register a marker
autoresearch detach        # Unregister a marker
autoresearch skip          # Skip current experiment
autoresearch pause         # Pause a marker
autoresearch finalize      # Clean branches from experiment history
autoresearch merge         # Merge finalized branch
autoresearch daemon start  # Scheduled overnight runs
```

All commands support `--headless` for JSON output.

---

## Production Results

Deployed on [antoncore](https://github.com/The-Cloud-Clock-Work/antoncore) (3.3k LOC Python monorepo):

| Run | Baseline | Result | Delta | Audit |
|-----|----------|--------|-------|-------|
| 1 | 186 errors | 163 | -23 | manual merge |
| 2 | 163 errors | 133 | -30 | PR #218 (merged) |
| 3 | 133 errors | 0 | -133 | PR #219 (merged) |

**186 → 0 ruff errors in 3 cycles.** Full GitHub PR audit trail.

---

## Architecture

```
src/autoresearch/
  cli.py             # 13 commands, interactive + headless
  engine.py          # Core loop + AgentRunner + auto-publish
  marker.py          # config.yaml schema (Pydantic)
  worktree.py        # Git worktree isolation
  metrics.py         # Metric extraction + MAD confidence
  program.py         # Runtime prompt generation
  agent_profile.py   # Claude Code settings + CLAUDE.md generation
  gates.py           # Security + test + confidence gates
  telemetry.py       # stream-json parsing
  daemon.py          # Cron scheduling
  skills/            # /onboard + /autoresearch Claude Code skills
  agents/default/    # Shipped agent profile
```

---

## Links

- **PyPI:** [tccw-autoresearch](https://pypi.org/project/tccw-autoresearch/)
- **Docs:** [the-cloud-clock-work.github.io/tccw-autoresearch](https://the-cloud-clock-work.github.io/tccw-autoresearch/)
- **SonarQube:** 94.8% coverage, 0 bugs, 0 vulnerabilities, 25 code smells

---

## License

MIT
