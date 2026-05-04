#!/usr/bin/env bash
set -euo pipefail

# Usage: 02_check_prerequisites.sh
# Checks that autoresearch and claude CLIs are available on PATH.
# Exits 0 if both found, 1 if either missing.

MISSING=0

if command -v autoresearch &>/dev/null; then
  echo "OK: autoresearch found ($(autoresearch --version 2>/dev/null || echo 'version unknown'))"
else
  echo "MISSING: autoresearch — run 'pip install -e .' from the tcc-autoresearch directory" >&2
  MISSING=1
fi

if command -v claude &>/dev/null; then
  echo "OK: claude found ($(claude --version 2>/dev/null || echo 'version unknown'))"
else
  echo "MISSING: claude — install from https://docs.anthropic.com/en/docs/claude-code" >&2
  MISSING=1
fi

exit "$MISSING"
