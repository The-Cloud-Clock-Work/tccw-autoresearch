# Telemetry & Results

> Telemetry, results tracking, `results.tsv`.

## Overview

The results module (`results.py`) tracks experiment outcomes in `results.tsv`. The telemetry module (`telemetry.py`) provides run-level metrics and cost tracking.

## Results Tracking

Each experiment appends a row to `results.tsv` with:

- Experiment number
- Timestamp
- Metric value (before/after)
- Whether changes were kept or discarded
- Commit hash (if kept)

## Result Queries

- `read_results()` — Load all results for a marker
- `get_latest_metric()` — Current best metric value
- `get_kept_metrics()` — All successful improvements
- `append_result()` — Record a new experiment outcome

## Telemetry

The `telemetry.py` module tracks:

- Total experiments run
- Success/failure rates
- Time and cost per experiment
- Cumulative improvement metrics
