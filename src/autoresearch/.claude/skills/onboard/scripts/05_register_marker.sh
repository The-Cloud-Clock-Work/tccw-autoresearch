#!/usr/bin/env bash
set -euo pipefail

REPO_PATH="${1:?Usage: 05_register_marker.sh <repo-path>}"

if ! command -v autoresearch &>/dev/null; then
    echo "ERROR: autoresearch CLI not found on PATH"
    exit 1
fi

echo "Registering markers from $REPO_PATH..."
autoresearch add --path "$REPO_PATH" 2>&1

echo "REGISTERED"
