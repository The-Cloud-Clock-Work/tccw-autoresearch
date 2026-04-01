# CLI

> CLI commands, interactive + headless modes.

## Overview

The CLI (`cli.py`) is built with Typer and Rich. Every command supports two modes:

- **Interactive** — Rich TUI with tables, menus, and color output
- **Headless** — `--headless` flag produces structured JSON for automation

## Commands

| Command | Purpose |
|---------|---------|
| `autoresearch` | Default: show status dashboard |
| `autoresearch run -m <marker>` | Run improvement loop for a marker |
| `autoresearch status` | Show all tracked markers and their states |
| `autoresearch results -m <marker>` | View experiment results |
| `autoresearch track -m <marker>` | Start tracking a marker |
| `autoresearch untrack -m <marker>` | Stop tracking a marker |
| `autoresearch set-status -m <marker> -s <status>` | Override marker status locally |

## Global Flags

| Flag | Purpose |
|------|---------|
| `--headless` | JSON output, no TUI |
| `--marker-file` | Path to `.autoresearch.yaml` |
| `-h`, `--help` | Help text |

## Headless Mode

When `--headless` is set, all output is structured JSON via `ok_json()` / `err_json()` helpers in `cli_utils.py`. Exit codes follow standard conventions (0 = success, 1 = error).
