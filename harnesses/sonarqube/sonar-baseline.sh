#!/usr/bin/env bash
set -euo pipefail

# sonar-baseline.sh — Get current SonarQube issue count for baseline
# Used when creating a new autoresearch marker.
#
# Usage: sonar-baseline.sh <project-key>
# Env:   SONAR_ADMIN_TOKEN (required)
# Output: "baseline_issues: <N>"

PROJECT_KEY="${1:?Usage: sonar-baseline.sh <project-key>}"

ANTON_HOST="root@10.10.30.130"
SSH_KEY="$HOME/.ssh/anton_id_ed25519"
SONAR_TOKEN="${SONAR_ADMIN_TOKEN:?SONAR_ADMIN_TOKEN env var required}"

SQ_IP=$(ssh -i "$SSH_KEY" "$ANTON_HOST" \
  "docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' sonarqube_server")

METRICS=$(ssh -i "$SSH_KEY" "$ANTON_HOST" \
  "curl -s -u '${SONAR_TOKEN}:' \
  'http://${SQ_IP}:9000/api/measures/component?component=${PROJECT_KEY}&metricKeys=bugs,vulnerabilities,code_smells'" \
  | python3 -c "
import sys, json
data = json.load(sys.stdin)
measures = {m['metric']: int(m['value']) for m in data['component']['measures']}
bugs = measures.get('bugs', 0)
vulns = measures.get('vulnerabilities', 0)
smells = measures.get('code_smells', 0)
total = bugs + vulns + smells
print(f'bugs: {bugs}')
print(f'vulnerabilities: {vulns}')
print(f'code_smells: {smells}')
print(f'baseline_issues: {total}')
")

echo "$METRICS"
