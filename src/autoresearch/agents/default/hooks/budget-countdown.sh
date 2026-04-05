#!/usr/bin/env bash
set -euo pipefail

# budget-countdown.sh — PostToolUse hook for autoresearch agents
# Outputs JSON additionalContext with remaining budget time.
# Engine sets AUTORESEARCH_BUDGET_END (unix timestamp) before spawning agent.

BUDGET_END="${AUTORESEARCH_BUDGET_END:-0}"

if [[ "${BUDGET_END}" == "0" ]]; then
  exit 0
fi

NOW=$(date +%s)
REMAINING=$((BUDGET_END - NOW))

if [[ "${REMAINING}" -le 0 ]]; then
  MSG="▲▲▲ BUDGET EXPIRED — COMMIT NOW AND EXIT ▲▲▲"
elif [[ "${REMAINING}" -le 120 ]]; then
  MINS=$((REMAINING / 60))
  SECS=$((REMAINING % 60))
  MSG="▲▲▲ BUDGET: ${MINS}m${SECS}s — STOP EDITING, COMMIT NOW, EXIT ▲▲▲"
elif [[ "${REMAINING}" -le 300 ]]; then
  MINS=$((REMAINING / 60))
  SECS=$((REMAINING % 60))
  MSG="▲ BUDGET: ${MINS}m${SECS}s remaining — wrap up and commit soon"
else
  MINS=$((REMAINING / 60))
  MSG="BUDGET: ${MINS}m remaining"
fi

echo "{\"hookSpecificOutput\": {\"hookEventName\": \"PostToolUse\", \"additionalContext\": \"${MSG}\"}}"
