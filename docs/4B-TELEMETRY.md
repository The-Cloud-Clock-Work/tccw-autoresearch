---
layout: default
title: Telemetry
parent: Documentation Index
nav_order: 41
---

# Telemetry & Results

> Telemetry, results tracking, `results.tsv`.

## Overview

The results module (`results.py`) tracks experiment outcomes in `results.tsv`. The telemetry module (`telemetry.py`) provides run-level metrics and cost tracking.

## Results Tracking

Each experiment appends a row to `results.tsv` with these columns:

| Column | Description |
|--------|-------------|
| `commit` | Git commit hash (if kept) or `--` (if discarded) |
| `metric` | Measured metric value |
| `guard` | Guard result or `--` if no guard configured |
| `status` | `kept` or `discarded` |
| `confidence` | Statistical confidence score |
| `description` | One-line summary of the change |

## Result Queries

- `read_results()` — Load all results for a marker
- `get_latest_metric()` — Current best metric value
- `get_kept_metrics()` — All successful improvements
- `append_result()` — Record a new experiment outcome

## Telemetry

The `telemetry.py` module parses Claude Code's `--output-format stream-json` into a `TelemetryReport` dataclass covering tokens, cost, tools used, and errors.
