#!/usr/bin/env bash
set -euo pipefail

# 10_marker_status.sh — Auto-detect marker, show config + state + results
# No hardcoded paths. Works from any repo with .autoresearch/config.yaml.

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
CONFIG="${REPO_ROOT}/.autoresearch/config.yaml"

if [[ ! -f "$CONFIG" ]]; then
    echo "ERROR: No .autoresearch/config.yaml found at ${REPO_ROOT}"
    echo "Run: autoresearch init --path ${REPO_ROOT}"
    exit 1
fi

# Auto-detect marker name from config
MARKER_NAME=$(grep -m1 '^\s*-\?\s*name:' "$CONFIG" | sed 's/.*name:\s*//' | tr -d '"' | tr -d "'")
REPO_NAME=$(basename "$REPO_ROOT")
MARKER="${REPO_NAME}:${MARKER_NAME}"

echo "=== MARKER: ${MARKER} ==="
echo ""

# --- Config summary ---
echo "--- CONFIG ---"
echo "Repo:     ${REPO_ROOT}"
echo "Marker:   ${MARKER_NAME}"

METRIC_CMD=$(grep -A5 'metric:' "$CONFIG" | grep 'command:' | head -1 | sed 's/.*command:\s*//' | tr -d '"')
METRIC_DIR=$(grep -A5 'metric:' "$CONFIG" | grep 'direction:' | head -1 | sed 's/.*direction:\s*//' | tr -d '"')
BASELINE=$(grep -A5 'metric:' "$CONFIG" | grep 'baseline:' | head -1 | sed 's/.*baseline:\s*//')
BUDGET=$(grep -A3 'loop:' "$CONFIG" | grep 'budget_per_experiment:' | head -1 | sed 's/.*budget_per_experiment:\s*//')
MAX_EXP=$(grep -A3 'loop:' "$CONFIG" | grep 'max_experiments:' | head -1 | sed 's/.*max_experiments:\s*//')
AUTO_MERGE=$(grep -A3 'auto_merge:' "$CONFIG" | grep 'enabled:' | head -1 | sed 's/.*enabled:\s*//')
TARGET_BR=$(grep -A3 'auto_merge:' "$CONFIG" | grep 'target_branch:' | head -1 | sed 's/.*target_branch:\s*//')

echo "Metric:   ${METRIC_CMD:-unknown}"
echo "Direction: ${METRIC_DIR:-unknown}"
echo "Baseline: ${BASELINE:-unknown}"
echo "Budget:   ${BUDGET:-unknown}"
echo "Max exp:  ${MAX_EXP:-unknown}"
echo "Auto-merge: ${AUTO_MERGE:-false} → ${TARGET_BR:-dev}"
echo ""

# --- Current metric ---
echo "--- CURRENT METRIC ---"
if [[ -n "${METRIC_CMD:-}" ]]; then
    EXTRACT=$(grep -A5 'metric:' "$CONFIG" | grep 'extract:' | head -1 | sed "s/.*extract:\s*//" | tr -d "'" | tr -d '"')
    CURRENT=$(cd "$REPO_ROOT" && eval "$METRIC_CMD" 2>&1 | grep -oP "$EXTRACT" || echo "FAILED")
    echo "Current: ${CURRENT}"
else
    echo "ERROR: No metric command found in config"
fi
echo ""

# --- State from state.json ---
echo "--- STATE ---"
STATE_FILE="${HOME}/.autoresearch/state.json"
if [[ -f "$STATE_FILE" ]]; then
    python3 -c "
import json, sys
state = json.load(open('${STATE_FILE}'))
markers = state.get('tracked_markers', [])
found = [m for m in markers if m.get('id', '') == '${MARKER}' or m.get('marker_name', '') == '${MARKER_NAME}']
if not found:
    print('Marker not registered in state.json')
    print('Run: autoresearch add --path ${REPO_ROOT}')
    sys.exit(0)
m = found[0]
print(f'Status:      {m.get(\"status\", \"unknown\")}')
print(f'Last run:    {m.get(\"last_run\", \"never\")}')
print(f'Repo path:   {m.get(\"repo_path\", \"unknown\")}')
" 2>/dev/null || echo "ERROR: Failed to parse state.json"
else
    echo "No state.json found at ${STATE_FILE}"
    echo "Run: autoresearch add --path ${REPO_ROOT}"
fi
echo ""

# --- Results TSV ---
echo "--- RESULTS ---"
RESULTS_TSV="${REPO_ROOT}/.autoresearch/${MARKER_NAME}/results.tsv"
if [[ -f "$RESULTS_TSV" ]]; then
    TOTAL=$(wc -l < "$RESULTS_TSV")
    echo "Total rows: $((TOTAL - 1))"
    echo ""
    head -1 "$RESULTS_TSV"
    tail -10 "$RESULTS_TSV"
else
    echo "No results yet at ${RESULTS_TSV}"
fi
