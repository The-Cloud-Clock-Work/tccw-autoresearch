#!/usr/bin/env bash
set -euo pipefail

# Usage: 04_measure_baseline.sh <repo-path> <metric-command> <extract-command>
# Runs the metric command in the target repo and extracts a single number.
# Outputs the extracted baseline value.

REPO_PATH="${1:?Usage: 04_measure_baseline.sh <repo-path> <metric-command> <extract-command>}"
METRIC_CMD="${2:?Missing metric command}"
EXTRACT_CMD="${3:?Missing extract command}"

cd "$REPO_PATH"

OUTPUT=$(eval "$METRIC_CMD" 2>&1) || true
BASELINE=$(echo "$OUTPUT" | eval "$EXTRACT_CMD" 2>/dev/null || echo "")

if [[ -z "$BASELINE" ]]; then
  echo "ERROR: Could not extract baseline from metric output" >&2
  echo "Raw output:" >&2
  echo "$OUTPUT" >&2
  exit 1
fi

echo "$BASELINE"
