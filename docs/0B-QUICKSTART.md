# Quickstart

> Installation, first marker, first run.

## Installation

```bash
pip install -e ".[dev]"
```

Requires Python 3.10+. Dependencies: `pydantic`, `pyyaml`, `rich`, `typer`, `croniter`.

## Create a Marker

Add `.autoresearch.yaml` to your repository root:

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
      command: "pytest tests/test_main.py -q"
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
autoresearch run -m my-first-marker

# Headless mode (CI/CD, automation)
autoresearch run -m my-first-marker --headless
```

## Check Status

```bash
autoresearch status
autoresearch status -m my-first-marker
```

## View Results

```bash
autoresearch results -m my-first-marker
```
