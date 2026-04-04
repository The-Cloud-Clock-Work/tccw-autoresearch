# Configuration

> Global config, `~/.autoresearch/`, env vars.

## Overview

The config module (`config.py`) manages global configuration stored in `~/.autoresearch/`.

## Directory Structure

```
~/.autoresearch/
├── config.yaml      # Global defaults
├── state.json       # Tracked markers and overrides
└── ...
```

## Local Config

Per-repo configuration lives in `.autoresearch/config.yaml` alongside the marker file.

## Auto-Merge Config

The `auto_merge` section in the marker controls post-experiment behavior:

```yaml
auto_merge:
  enabled: false              # Enable gate chain + merge
  target_branch: dev          # Branch to merge into
  gates:                      # Gate chain (short-circuits on first failure)
    - security
    - tests
    - confidence
  security_command: null      # Shell command for security gate
  test_command: null          # Shell command for test gate
  min_confidence: 1.0         # Minimum confidence score
  push_to_remote: false       # git push after merge
  create_pr: false            # gh pr create after push
  snapshot_command: null       # Pre-experiment hook (see below)
  restore_command: null        # Post-failure hook (see below)
  notify: []                  # Notification targets
```

### Lifecycle Hooks

`snapshot_command` and `restore_command` are generic shell hooks:

- **`snapshot_command`** — Runs before each experiment. Last stdout line = snapshot reference. `{exp_num}` placeholder replaced with experiment number.
- **`restore_command`** — Runs after experiment failure (crash, metric, guard). `{snapshot_id}` placeholder replaced with value from snapshot_command.

Both are optional, have a 120s timeout, and never crash the engine on failure.

See [Engine Hooks](1B-ENGINE.md#lifecycle-hooks) for full documentation, flow diagram, and examples.

## Environment Variables

Credentials and secrets must be configured as environment variables — never hardcoded. The engine passes the current environment to harness subprocesses.
