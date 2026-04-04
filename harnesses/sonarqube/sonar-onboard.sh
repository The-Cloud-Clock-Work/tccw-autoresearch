#!/usr/bin/env bash
set -euo pipefail

# sonar-onboard.sh — Onboard a repo into the SonarQube autoresearch loop
#
# Usage: sonar-onboard.sh <repo-path> <project-key>
# Env:   SONAR_ADMIN_TOKEN (required)
#
# Steps:
#   1. Verify sonar-project.properties exists in repo
#   2. Run sonar-baseline.sh to get current issue count
#   3. Generate .autoresearch/config.yaml with correct baseline
#   4. Report next steps

REPO_PATH="${1:?Usage: sonar-onboard.sh <repo-path> <project-key>}"
PROJECT_KEY="${2:?Provide SonarQube project key}"

HARNESS_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_PATH="$(cd "$REPO_PATH" && pwd)"
REPO_NAME="$(basename "$REPO_PATH")"

echo "▬ SonarQube Autoresearch Onboarding"
echo "  Repo: ${REPO_PATH}"
echo "  Project: ${PROJECT_KEY}"
echo ""

# --- 1. Verify sonar-project.properties ---
if [[ ! -f "${REPO_PATH}/sonar-project.properties" ]]; then
  echo "ERROR: ${REPO_PATH}/sonar-project.properties not found"
  echo "Run 'sonar-onboard' MCP tool to create the SonarQube project first."
  exit 1
fi
echo "  [1/4] sonar-project.properties found"

# --- 2. Get baseline ---
echo "  [2/4] Fetching baseline from SonarQube..."
BASELINE_OUTPUT=$("${HARNESS_DIR}/sonar-baseline.sh" "$PROJECT_KEY")
BASELINE=$(echo "$BASELINE_OUTPUT" | grep -oP 'baseline_issues: \K\d+')

if [[ -z "$BASELINE" ]]; then
  echo "ERROR: Could not fetch baseline. Is the project scanned?"
  echo "Output: ${BASELINE_OUTPUT}"
  exit 1
fi
echo "  Baseline: ${BASELINE} issues"
echo "$BASELINE_OUTPUT" | grep -v baseline_issues | sed 's/^/    /'

# --- 3. Detect mutable patterns ---
MUTABLE_PATTERNS=""
if [[ -d "${REPO_PATH}/src" ]]; then
  MUTABLE_PATTERNS="        - \"src/**/*.py\""
fi
if [[ -d "${REPO_PATH}/mcp" ]]; then
  MUTABLE_PATTERNS="${MUTABLE_PATTERNS}
        - \"mcp/**/*.py\""
fi
if [[ -d "${REPO_PATH}/stacks" ]]; then
  MUTABLE_PATTERNS="${MUTABLE_PATTERNS}
        - \"stacks/**/*.py\""
fi
if [[ -d "${REPO_PATH}/packages" ]]; then
  MUTABLE_PATTERNS="${MUTABLE_PATTERNS}
        - \"packages/**/*.py\""
fi
if [[ -d "${REPO_PATH}/automation" ]]; then
  MUTABLE_PATTERNS="${MUTABLE_PATTERNS}
        - \"automation/**/*.py\""
fi
if [[ -d "${REPO_PATH}/tests" ]]; then
  MUTABLE_PATTERNS="${MUTABLE_PATTERNS}
        - \"tests/**/*.py\""
fi
# Fallback
if [[ -z "$MUTABLE_PATTERNS" ]]; then
  MUTABLE_PATTERNS="        - \"**/*.py\""
fi

# --- 4. Generate config ---
echo "  [3/4] Generating .autoresearch/config.yaml..."
mkdir -p "${REPO_PATH}/.autoresearch"

cat > "${REPO_PATH}/.autoresearch/config.yaml" << EOF
markers:
  - name: sonar-quality
    description: "Reduce SonarQube issues (bugs, vulnerabilities, code smells)"
    status: active
    target:
      mutable:
${MUTABLE_PATTERNS}
      immutable:
        - sonar-project.properties
        - .autoresearch/config.yaml
    metric:
      command: "bash ${HARNESS_DIR}/sonar-scan.sh ${PROJECT_KEY} ."
      extract: "grep -oP 'total_issues: \\\\K\\\\d+'"
      direction: lower
      baseline: ${BASELINE}
      target: 0
    guard:
      command: "bash ${HARNESS_DIR}/sonar-gate.sh ${PROJECT_KEY}"
      rework_attempts: 2
    loop:
      model: sonnet
      budget_per_experiment: 15m
      max_experiments: 20
    escalation:
      refine_after: 3
      pivot_after: 5
      search_after_pivots: 2
      halt_after_pivots: 3
    agent:
      name: sonar-fixer
      model: sonnet
      effort: medium
      permission_mode: bypassPermissions
      allowed_tools:
        - "Bash(python3 *)"
        - "Bash(pytest *)"
        - "Bash(ruff *)"
      disallowed_tools:
        - "Bash(rm *)"
        - "Bash(git push *)"
        - "Bash(curl *)"
    schedule:
      type: on-demand
EOF

echo "  [4/4] Config written"
echo ""
echo "▬ Onboarding complete"
echo "  Config: ${REPO_PATH}/.autoresearch/config.yaml"
echo "  Baseline: ${BASELINE} issues (bugs + vulnerabilities + code_smells)"
echo ""
echo "  Next steps:"
echo "    autoresearch track ${REPO_PATH}"
echo "    autoresearch run ${REPO_NAME}:sonar-quality --max-experiments 1"
