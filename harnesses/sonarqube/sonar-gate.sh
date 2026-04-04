#!/usr/bin/env bash
set -euo pipefail

# sonar-gate.sh — Autoresearch guard command
# Checks SonarQube quality gate status for a project.
# Exit 0 = pass, Exit 1 = fail.
#
# Usage: sonar-gate.sh <project-key>
# Env:   SONAR_ADMIN_TOKEN (required)

PROJECT_KEY="${1:?Usage: sonar-gate.sh <project-key>}"

ANTON_HOST="root@10.10.30.130"
SSH_KEY="$HOME/.ssh/anton_id_ed25519"
SONAR_TOKEN="${SONAR_ADMIN_TOKEN:?SONAR_ADMIN_TOKEN env var required}"

SQ_IP=$(ssh -i "$SSH_KEY" "$ANTON_HOST" \
  "docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' sonarqube_server")

STATUS=$(ssh -i "$SSH_KEY" "$ANTON_HOST" \
  "curl -s -u '${SONAR_TOKEN}:' \
  'http://${SQ_IP}:9000/api/qualitygates/project_status?projectKey=${PROJECT_KEY}'" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['projectStatus']['status'])")

if [[ "$STATUS" == "OK" ]]; then
  echo "quality_gate: PASS"
  exit 0
else
  echo "quality_gate: FAIL (${STATUS})"
  exit 1
fi
