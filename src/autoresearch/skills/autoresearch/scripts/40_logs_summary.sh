#!/usr/bin/env bash
set -euo pipefail

# 40_logs_summary.sh — Experiment history, kept commits, agent logs
# No hardcoded paths. Works from any repo with .autoresearch/config.yaml.

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
CONFIG="${REPO_ROOT}/.autoresearch/config.yaml"

if [[ ! -f "$CONFIG" ]]; then
    echo "ERROR: No .autoresearch/config.yaml found at ${REPO_ROOT}"
    exit 1
fi

MARKER_NAME=$(grep -m1 '^\s*-\?\s*name:' "$CONFIG" | sed 's/.*name:\s*//' | tr -d '"' | tr -d "'")
TARGET_BRANCH=$(grep -A3 'auto_merge:' "$CONFIG" | grep 'target_branch:' | head -1 | sed 's/.*target_branch:\s*//' || echo "dev")
TARGET_BRANCH="${TARGET_BRANCH:-dev}"

# --- Results TSV ---
echo "=== RESULTS ==="
RESULTS_TSV="${REPO_ROOT}/.autoresearch/${MARKER_NAME}/results.tsv"
if [[ -f "$RESULTS_TSV" ]]; then
    TOTAL=$(wc -l < "$RESULTS_TSV")
    echo "File: ${RESULTS_TSV}"
    echo "Total rows: $((TOTAL - 1))"
    echo ""
    cat "$RESULTS_TSV"
else
    echo "No results file at ${RESULTS_TSV}"
fi
echo ""

# --- Git log: autoresearch commits ---
echo "=== AUTORESEARCH COMMITS ==="
cd "$REPO_ROOT"
git log --oneline --all --grep="autoresearch" -20 2>/dev/null || echo "No autoresearch commits found"
echo ""

# --- Last 10 commits on target branch ---
echo "=== LAST 10 COMMITS (${TARGET_BRANCH}) ==="
git log --oneline "${TARGET_BRANCH}" -10 2>/dev/null || echo "Branch ${TARGET_BRANCH} not found"
echo ""

# --- Worktrees ---
echo "=== WORKTREES ==="
git worktree list 2>/dev/null || echo "No worktrees"
echo ""

# --- Agent logs ---
echo "=== AGENT LOGS ==="
LOGS_DIR="${REPO_ROOT}/.autoresearch/${MARKER_NAME}/logs"
LOGS_DIR2="${REPO_ROOT}/.autoresearch/agents/${MARKER_NAME}/logs"
LOGS_DIR3="${HOME}/.autoresearch/agents/${MARKER_NAME}/logs"

FOUND_LOGS=""
for d in "$LOGS_DIR" "$LOGS_DIR2" "$LOGS_DIR3"; do
    if [[ -d "$d" ]]; then
        FOUND_LOGS="$d"
        break
    fi
done

if [[ -n "$FOUND_LOGS" ]]; then
    echo "Log dir: ${FOUND_LOGS}"
    LATEST=$(ls -t "$FOUND_LOGS"/*.jsonl 2>/dev/null | head -1)
    if [[ -n "$LATEST" ]]; then
        echo "Latest: $(basename "$LATEST")"
        SIZE=$(wc -c < "$LATEST")
        LINES=$(wc -l < "$LATEST")
        echo "Size: ${SIZE} bytes, ${LINES} lines"
        echo ""
        echo "--- Last 5 lines ---"
        tail -5 "$LATEST"
    else
        echo "No .jsonl log files found"
    fi
else
    echo "No agent log directories found"
fi
