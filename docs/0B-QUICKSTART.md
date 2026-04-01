# Quickstart

> Installation, first marker, first run.

## Installation

```bash
pip install -e ".[dev]"
```

Requires Python 3.10+, plus [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (`claude` CLI) on PATH.

## Initialize Your Repo

```bash
cd /path/to/your-project
autoresearch init
```

This creates `.autoresearch/config.yaml` with a starter marker and `.autoresearch/agents/` with the default agent profile.

## Configure Your Marker

Edit `.autoresearch/config.yaml`:

```yaml
markers:
  - name: my-first-marker
    description: Improve test pass rate
    status: active
    target:
      mutable:
        - src/**/*.py
      immutable:
        - tests/test_main.py
    metric:
      command: "pytest tests/test_main.py -q --tb=no 2>&1 | tail -1"
      extract: "grep -oP '\\d+(?= passed)'"
      direction: higher
      baseline: 10
    loop:
      model: sonnet
      budget_per_experiment: 10m
      max_experiments: 20
```

## Run

```bash
# Interactive mode
autoresearch run -m my-project:my-first-marker

# Headless mode (CI/CD, automation)
autoresearch run -m my-project:my-first-marker --headless
```

Note: marker IDs use the format `repo_name:marker_name`.

## Check Status

```bash
autoresearch status -m my-project:my-first-marker
autoresearch results -m my-project:my-first-marker
```
