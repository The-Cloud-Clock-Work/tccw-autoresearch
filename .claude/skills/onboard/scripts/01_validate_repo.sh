#!/usr/bin/env bash
set -euo pipefail

# Usage: 01_validate_repo.sh <repo-path>
# Validates that the target path is a git repo with recognizable project structure.
# Exits 0 on success, 1 with error message on failure.

REPO_PATH="${1:?Usage: 01_validate_repo.sh <repo-path>}"

if [[ ! -d "$REPO_PATH" ]]; then
  echo "ERROR: Directory does not exist: $REPO_PATH" >&2
  exit 1
fi

if ! git -C "$REPO_PATH" rev-parse --git-dir &>/dev/null; then
  echo "ERROR: Not a git repository: $REPO_PATH" >&2
  exit 1
fi

FOUND=0
for marker in src lib packages app cmd internal Makefile package.json pyproject.toml Cargo.toml go.mod docker-compose.yml compose.yml setup.py setup.cfg CMakeLists.txt pom.xml build.gradle; do
  if [[ -e "$REPO_PATH/$marker" ]]; then
    FOUND=1
    break
  fi
done

if [[ "$FOUND" -eq 0 ]]; then
  echo "WARNING: No recognizable project structure found in $REPO_PATH — proceeding anyway" >&2
fi

echo "OK: $REPO_PATH is a valid git repository"
