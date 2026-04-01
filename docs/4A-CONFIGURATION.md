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

## Environment Variables

Credentials and secrets must be configured as environment variables — never hardcoded. The engine passes the current environment to harness subprocesses.
