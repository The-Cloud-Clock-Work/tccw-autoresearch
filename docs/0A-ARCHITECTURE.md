# Architecture

> System architecture, core loop, and design principles for tccw-autoresearch.

## Overview

tccw-autoresearch is an **agnostic autonomous improvement engine** that implements the Karpathy autoresearch loop pattern for any codebase. It edits target files, runs an immutable harness, measures a single metric, keeps improvements, and discards regressions.

## Core Loop

```
LOOP:
  1. Generate improvement idea (AI agent)
  2. Edit mutable target files
  3. Run immutable harness (metric command)
  4. Extract metric value
  5. If improved → git commit, record result
  6. If worse → git reset, record result
  7. If guard fails → attempt rework (up to N times)
  8. REPEAT until budget exhausted or target reached
```

## Hard Dependency: Claude Code

AutoResearch is an **orchestrator**, not a code editor. The actual code changes are performed by [Claude Code](https://docs.anthropic.com/en/docs/claude-code) agents (`claude` CLI), spawned as subprocesses.

```
autoresearch (orchestrator)
  └── claude (agent) ← hard dependency, does the actual coding
        ├── reads mutable target files
        ├── edits code based on improvement ideas
        ├── runs the metric harness
        └── commits changes if improved
```

The engine passes each agent:
- **Mutable/immutable file rules** — translated to `--allowedTools` / `--disallowedTools` CLI flags
- **Agent profile** — CLAUDE.md, rules, and settings from `.autoresearch/agents/`
- **Program** — generated instructions describing what to attempt

Without `claude` on PATH, the engine cannot run experiments.

## Key Design Principles

- **The repo is the engine** — `.autoresearch.yaml` carries everything needed to run
- **Agnostic** — no stack-specific, provider-specific, or infrastructure-specific code
- **Dual-mode CLI** — every command works interactively (TUI) and headlessly (JSON)
- **Marker-driven** — markers declare what to improve; the engine executes
- **Worktree isolation** — each marker runs in its own git worktree

## Module Map

| Module | Purpose |
|--------|---------|
| `cli.py` | CLI entry point (Typer + Rich) |
| `engine.py` | Core experiment loop |
| `marker.py` | `.autoresearch.yaml` parser + Pydantic schema |
| `metrics.py` | Metric extraction + guard gates |
| `state.py` | `state.json` management |
| `worktree.py` | Git worktree lifecycle |
| `daemon.py` | Background daemon service |
| `results.py` | `results.tsv` tracking |
| `ideas.py` | Idea generation + history |
| `program.py` | Program synthesis for experiments |
| `config.py` | Global config (`~/.autoresearch/`) |
| `telemetry.py` | Run telemetry and cost tracking |
| `agent_profile.py` | Agent profile loading |

## Data Flow

```
.autoresearch.yaml → marker.py → engine.py → worktree.py (isolate)
                                     ↓
                              metrics.py (measure)
                                     ↓
                              results.py (record)
                                     ↓
                              state.py (persist)
```
