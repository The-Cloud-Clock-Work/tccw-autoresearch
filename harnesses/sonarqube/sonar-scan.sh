#!/usr/bin/env bash
set -euo pipefail

# sonar-scan.sh — Autoresearch metric command
# Runs SonarQube scanner on worktree code via SSH+Docker on Anton,
# waits for analysis completion, then extracts total issue count.
#
# Usage: sonar-scan.sh <project-key> [source-dir]
# Env:   SONAR_ADMIN_TOKEN (required)
# Output: "total_issues: <N>" on stdout (parsed by metric.extract)

PROJECT_KEY="${1:?Usage: sonar-scan.sh <project-key> [source-dir]}"
SOURCE_DIR="${2:-.}"

ANTON_HOST="root@10.10.30.130"
SSH_KEY="$HOME/.ssh/anton_id_ed25519"
SONAR_TOKEN="${SONAR_ADMIN_TOKEN:?SONAR_ADMIN_TOKEN env var required}"

SCAN_DIR="/tmp/sonar-autoresearch-$$"
MAX_WAIT=120
POLL_INTERVAL=5

# --- 1. Rsync worktree to Anton ---
echo "sonar-scan: rsyncing ${SOURCE_DIR} to ${ANTON_HOST}:${SCAN_DIR}/" >&2
rsync -az -e "ssh -i ${SSH_KEY}" \
  --exclude='.git' \
  --exclude='node_modules' \
  --exclude='__pycache__' \
  --exclude='.venv' \
  --exclude='runtime' \
  --exclude='data' \
  "${SOURCE_DIR}/" "${ANTON_HOST}:${SCAN_DIR}/"

# --- 2. Run sonar-scanner via Docker on Anton ---
echo "sonar-scan: running scanner on Anton..." >&2
ssh -i "$SSH_KEY" "$ANTON_HOST" "
  SQ_IP=\$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' sonarqube_server)
  docker run --rm --network anton_net \
    -v ${SCAN_DIR}:/src -w /src \
    sonarsource/sonar-scanner-cli:latest \
    -Dsonar.host.url=http://\${SQ_IP}:9000 \
    -Dsonar.token=${SONAR_TOKEN} \
    -Dsonar.projectKey=${PROJECT_KEY} 2>&1 | tail -5
" >&2

# --- 3. Wait for CE analysis to complete ---
echo "sonar-scan: waiting for analysis to complete..." >&2
SQ_IP=$(ssh -i "$SSH_KEY" "$ANTON_HOST" \
  "docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' sonarqube_server")

WAITED=0
while [[ "$WAITED" -lt "$MAX_WAIT" ]]; do
  CE_STATUS=$(ssh -i "$SSH_KEY" "$ANTON_HOST" \
    "curl -s -u '${SONAR_TOKEN}:' 'http://${SQ_IP}:9000/api/ce/component?component=${PROJECT_KEY}'" \
    | python3 -c "
import sys, json
data = json.load(sys.stdin)
current = data.get('current', {})
if current:
    print(current.get('status', 'UNKNOWN'))
else:
    queue = data.get('queue', [])
    if queue:
        print(queue[0].get('status', 'UNKNOWN'))
    else:
        print('NONE')
" 2>/dev/null || echo "ERROR")

  if [[ "$CE_STATUS" == "SUCCESS" ]] || [[ "$CE_STATUS" == "NONE" ]]; then
    break
  elif [[ "$CE_STATUS" == "FAILED" ]]; then
    echo "sonar-scan: CE task FAILED" >&2
    ssh -i "$SSH_KEY" "$ANTON_HOST" "rm -rf ${SCAN_DIR}" 2>/dev/null || true
    exit 1
  fi

  sleep "$POLL_INTERVAL"
  WAITED=$((WAITED + POLL_INTERVAL))
done

# --- 4. Extract metrics ---
METRICS=$(ssh -i "$SSH_KEY" "$ANTON_HOST" \
  "curl -s -u '${SONAR_TOKEN}:' \
  'http://${SQ_IP}:9000/api/measures/component?component=${PROJECT_KEY}&metricKeys=bugs,vulnerabilities,code_smells'" \
  | python3 -c "
import sys, json
data = json.load(sys.stdin)
measures = {m['metric']: int(m['value']) for m in data['component']['measures']}
total = measures.get('bugs', 0) + measures.get('vulnerabilities', 0) + measures.get('code_smells', 0)
print(f'bugs: {measures.get(\"bugs\", 0)}')
print(f'vulnerabilities: {measures.get(\"vulnerabilities\", 0)}')
print(f'code_smells: {measures.get(\"code_smells\", 0)}')
print(f'total_issues: {total}')
")

echo "$METRICS"

# --- 5. Cleanup ---
ssh -i "$SSH_KEY" "$ANTON_HOST" "rm -rf ${SCAN_DIR}" 2>/dev/null || true

echo "sonar-scan: complete" >&2
