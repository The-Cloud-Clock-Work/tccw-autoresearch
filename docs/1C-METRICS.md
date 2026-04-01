# Metrics

> Metric extraction, guard gates, dual-gate verification.

## Overview

The metrics module (`metrics.py`) handles running harness commands, extracting numeric values, and evaluating guard conditions.

## Harness Execution

The `metric.command` from the marker is executed as a shell command in the worktree directory. Output is captured and passed through the `metric.extract` pattern to produce a single numeric value.

## Dual-Gate Verification

Each experiment can be validated by two independent gates:

1. **Metric gate** — Did the primary metric improve (based on `direction`)?
2. **Guard gate** — Does the broader test suite still pass (based on `guard.threshold`)?

Both must pass for changes to be kept.

## Confidence Scoring

The engine computes confidence levels for metric measurements to account for noisy metrics. This helps distinguish genuine improvements from statistical noise.

## Direction

- `higher` — larger values are better (e.g., test pass count, coverage %)
- `lower` — smaller values are better (e.g., build time, error count)
