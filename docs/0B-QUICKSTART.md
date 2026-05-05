---
layout: default
title: Quick Start
parent: Documentation Index
nav_order: 3
---

# Quickstart

> Install, onboard, run. Three commands.

## Install

```bash
pip install tcc-autoresearch
```

Requires Python 3.10+ and [Claude Code](https://docs.anthropic.com/en/docs/claude-code) on PATH.

## Onboard Your Repo

```bash
cd /path/to/your-project
autoresearch init
```

Claude opens interactively. It scans your project, asks what you want to improve, configures the marker, and measures your baseline. Everything is written to `.autoresearch/config.yaml`.

Use `--no-claude` to skip the wizard and edit config manually.

## Run

```bash
# Run all active markers (auto-discovers config in current directory)
autoresearch run

# Run a specific marker
autoresearch run -m my-marker

# Headless mode (CI/CD, automation)
autoresearch --headless run
```

No registration needed. The CLI reads `.autoresearch/config.yaml` from the current directory.

## Interactive TUI

```bash
autoresearch
```

Shows a numbered menu with your markers. Select to run, check status, or reconfigure.

## Check Results

```bash
autoresearch status -m my-marker
autoresearch results -m my-marker
```

## Clean Up Branches

```bash
autoresearch clean              # delete stale experiment branches (keeps latest)
autoresearch clean --remote     # also delete remote branches
autoresearch clean --dry-run    # preview what would be deleted
```

## Scheduled Runs (Daemon)

```bash
autoresearch daemon start    # runs experiments on schedule
autoresearch daemon status   # check if running
autoresearch daemon stop     # stop the daemon
```

Set `schedule.type` in config: `on-demand`, `overnight` (1am daily), `weekend` (Saturday 1am), or `cron` with a custom expression.
