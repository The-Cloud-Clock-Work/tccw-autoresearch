---
layout: default
title: CLI
parent: Documentation Index
nav_order: 20
---

# CLI

> CLI commands, interactive + headless modes.

## Overview

The CLI (`cli.py`) is built with Typer and Rich. Every command supports two modes:

- **Interactive** — Rich TUI with tables, menus, and color output
- **Headless** — `--headless` flag produces structured JSON for automation

## Commands

| Command | Purpose |
|---------|---------|
| `autoresearch` | Default: interactive home screen (marker selection, action keys) |
| `autoresearch list` | List all tracked markers |
| `autoresearch status -m <repo:marker>` | Show detailed status for a marker |
| `autoresearch results -m <repo:marker>` | View experiment results |
| `autoresearch ideas -m <repo:marker>` | View ideas backlog |
| `autoresearch confidence -m <repo:marker>` | View statistical confidence scores |
| `autoresearch init` | Scaffold `.autoresearch/` with default config + agent profile |
| `autoresearch add` | Register a marker for tracking |
| `autoresearch detach` | Unregister a marker from tracking |
| `autoresearch skip -m <repo:marker>` | Set marker status to `skip` |
| `autoresearch pause -m <repo:marker>` | Set marker status to `paused` |
| `autoresearch run -m <repo:marker>` | Run improvement loop for a marker |
| `autoresearch finalize -m <repo:marker>` | Cherry-pick + squash winning commits into clean branch |
| `autoresearch merge -m <repo:marker>` | Merge finalized branch |
| `autoresearch daemon start\|stop\|status\|logs` | Daemon management |

## Global Flags

| Flag | Purpose |
|------|---------|
| `--headless` | JSON output, no TUI |
| `-h`, `--help` | Help text |

## Marker ID Format

Markers are referenced by full ID: `repo_name:marker_name` (e.g., `tccw-autoresearch:test-suite-health`).

## Headless Mode

When `--headless` is set, all output is structured JSON via `ok_json()` / `err_json()` helpers in `cli_utils.py`. Exit codes: 0 = success, 1 = error, 2 = usage error.
