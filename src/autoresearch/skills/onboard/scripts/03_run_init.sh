#!/usr/bin/env bash
set -euo pipefail

# Usage: 03_run_init.sh <repo-path>
# Runs autoresearch init in the target repo (headless mode).
# Exits 0 on success, 1 on failure.

REPO_PATH="${1:?Usage: 03_run_init.sh <repo-path>}"

if [[ -f "$REPO_PATH/.autoresearch/config.yaml" ]]; then
  echo "EXISTS: .autoresearch/config.yaml already present in $REPO_PATH"
  exit 0
fi

cd "$REPO_PATH" && autoresearch init --headless
