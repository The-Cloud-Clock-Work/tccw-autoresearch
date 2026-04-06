---
layout: default
title: CLI
parent: Documentation Index
nav_order: 20
---

# CLI

> All commands, interactive TUI, headless mode.

## Overview

Built with Typer + Rich. Every command supports `--headless` for JSON output.

The CLI is **CWD-aware** — run from any directory with `.autoresearch/config.yaml` and it auto-discovers markers. No registration needed.

## Commands

| Command | Purpose |
|---------|---------|
| `autoresearch` | Interactive TUI — discovers markers, numbered menu |
| `autoresearch init` | AI-guided setup (spawns Claude Code with `/onboard` skill) |
| `autoresearch run` | Run all active markers in current directory |
| `autoresearch run -m <name>` | Run a specific marker by name |
| `autoresearch status -m <name>` | Marker dashboard |
| `autoresearch results -m <name>` | Experiment history |
| `autoresearch confidence -m <name>` | Statistical confidence scores |
| `autoresearch ideas -m <name>` | Ideas backlog |
| `autoresearch clean` | Delete stale experiment branches (keeps latest) |
| `autoresearch clean --remote` | Also delete remote branches |
| `autoresearch finalize -m <name>` | Cherry-pick kept experiments into clean branch |
| `autoresearch merge -m <name>` | Merge finalized branch into target |
| `autoresearch add --path .` | Register marker in global state (for daemon) |
| `autoresearch detach -m <name>` | Unregister a marker |
| `autoresearch skip -m <name>` | Skip current experiment |
| `autoresearch pause -m <name>` | Pause a marker |
| `autoresearch daemon start` | Start scheduled overnight runs |
| `autoresearch daemon stop` | Stop the daemon |
| `autoresearch daemon status` | Check daemon health |
| `autoresearch daemon logs` | View daemon logs |

## Interactive TUI

Running `autoresearch` with no arguments opens the TUI:

```
agentihooks-bundle — 1 marker(s)
┌───┬──────────────┬────────┬───────────┬─────────────────────────────┐
│ # │ Marker       │ Status │ Direction │ Metric Command              │
├───┼──────────────┼────────┼───────────┼─────────────────────────────┤
│ 1 │ doc-coverage │ active │ higher    │ ls docs/skills/*.md ...     │
└───┴──────────────┴────────┴───────────┴─────────────────────────────┘

  1  Run doc-coverage
  2  Status
  3  Init / reconfigure
  4  Quit

Select [1/2/3/4]:
```

## Live Progress Panel

During experiment runs, a Rich panel shows real-time progress:

```
┌─ autoresearch ◼ my-repo:my-marker ──────────────────┐
│ Baseline: 1 → Current: 14 (higher)  ◼  Budget: 10m  │
│                                                      │
│ ▓▓▓▓▓▓▓▓▓░░░░░░░░░ 3/10  Kept: 1  Disc: 2  Crash: 0│
│                                                      │
│  #  Status   Metric  Delta  Description              │
│  1  KEEP        14    +13   Created 13 skill docs    │
│  2  DISCARD     14      0   All docs already exist   │
│  3  DISCARD     14      0   Nothing to improve       │
│  4  ⠋ running...                                     │
└──────────────────────────────────────────────────────┘
```

## Headless Mode

Add `--headless` before the subcommand for JSON output:

```bash
autoresearch --headless run -m my-marker
autoresearch --headless status -m my-marker
```

All output goes to stdout as structured JSON.

## CWD Resolution

The CLI resolves markers in this order:

1. **No `-m` flag**: load all active markers from `.autoresearch/config.yaml` in CWD
2. **`-m simple-name`**: find marker by name in CWD config
3. **`-m repo:name`**: look up in global state (for daemon/multi-repo use)
