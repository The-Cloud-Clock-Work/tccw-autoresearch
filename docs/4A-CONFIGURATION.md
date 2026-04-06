---
layout: default
title: Configuration
parent: Documentation Index
nav_order: 40
---

# Configuration

> Marker config, agent settings, environment, scheduling.

## The Config File

`.autoresearch/config.yaml` is the single source of truth. The CLI reads it from the current directory — no global registration needed.

```yaml
markers:
  - name: my-marker
    description: "What this marker improves"
    status: active          # active | skip | paused
    target:
      mutable: ["src/**/*.py"]
      immutable: ["tests/**/*.py"]
    metric:
      command: "ruff check src/ 2>&1"
      extract: "grep -oP 'Found \\K\\d+'"
      direction: lower      # lower | higher
      baseline: 42
      issues_command: "ruff check src/ --output-format concise | head -30"
    guard:
      command: "pytest tests/ -q --tb=no 2>&1 | tail -1"
      extract: "grep -oP '\\d+(?= passed)'"
      threshold: 10
      rework_attempts: 2
    agent:
      name: default
      model: sonnet          # Claude model (sonnet, opus, haiku)
      effort: medium         # low | medium | high
      permission_mode: bypassPermissions
      budget_per_experiment: 10m
      max_experiments: 10
      env_file: null         # path to .env file (relative to repo root)
      allowed_tools: []
      disallowed_tools: []
    auto_merge:
      enabled: false         # create and merge PRs automatically
      target_branch: main    # PR target branch
    schedule:
      type: on-demand        # on-demand | overnight | weekend | cron
```

## Agent Config

All agent execution settings live under `agent:`:

| Field | Default | Description |
|-------|---------|-------------|
| `name` | `default` | Agent profile name (maps to `.autoresearch/agents/<name>/`) |
| `model` | `sonnet` | Claude model |
| `effort` | `medium` | Claude effort level |
| `permission_mode` | `bypassPermissions` | Claude permission mode |
| `budget_per_experiment` | `10m` | Time limit per experiment |
| `max_experiments` | `50` | Max experiments per run |
| `env_file` | `null` | Path to `.env` file for project secrets |
| `allowed_tools` | `[]` | Additional tools to allow |
| `disallowed_tools` | `[]` | Tools to explicitly deny |

## Environment Variables

The engine builds the subprocess environment in layers (later wins):

1. **System `os.environ`** — inherits from parent process
2. **`settings.json` `env` block** — from agent profile
3. **`agent.env_file`** — project-wide `.env` file from marker config
4. **Agent dir `.env`** — agent-specific overrides
5. **`AUTORESEARCH_BUDGET_END`** — injected deadline timestamp

Use `env_file` for project secrets (API keys, database URLs). Never hardcode credentials in config.

## Auto-Merge

| Field | Default | Description |
|-------|---------|-------------|
| `enabled` | `false` | When true, PRs are auto-merged via `gh pr merge --squash` |
| `target_branch` | `main` | PR target. One branch, one PR — no intermediate branches |
| `gates` | all 5 | Gate chain: `metric`, `quality_gate`, `security`, `tests`, `confidence` |
| `security_command` | `null` | Shell command for security gate |
| `test_command` | `null` | Shell command for test gate |
| `min_confidence` | `1.0` | Minimum confidence score for confidence gate |

## Schedule

| Type | Cron | Description |
|------|------|-------------|
| `on-demand` | — | Manual only (`autoresearch run`) |
| `overnight` | `0 1 * * *` | Daily at 1am |
| `weekend` | `0 1 * * 6` | Saturday at 1am |
| `cron` | custom | Set `schedule.cron: "0 */6 * * *"` |

Start the daemon with `autoresearch daemon start` to enable scheduled runs.

## .gitignore

`autoresearch init` and the engine automatically create `.autoresearch/.gitignore`:

```
state.json
**/logs/
```

Agent config (`CLAUDE.md`, `settings.json`), audit trail (`results.tsv`, `ideas.md`, `run.log`) are committed. Only runtime logs are excluded.

## Directory Structure

```
.autoresearch/
├── config.yaml          # Marker definitions
├── .gitignore           # Excludes logs and state
├── agents/
│   └── default/         # Agent profile (shipped with package)
│       ├── CLAUDE.md    # Agent instructions
│       ├── settings.json # Permissions
│       └── .env.example  # Env var template
├── <marker-name>/
│   ├── results.tsv      # Experiment audit trail
│   ├── ideas.md         # Failed experiment learnings
│   └── run.log          # Run history
└── state.json           # Runtime state (gitignored)
```
