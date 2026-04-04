# SonarQube Harness — Autoresearch Engine

Deterministic harness scripts for using SonarQube as the autoresearch metric source.

## Metric

**Total issues** = bugs + vulnerabilities + code_smells (direction: lower)

The autoresearch engine edits code → triggers a SonarQube scan → extracts the total issue count. If issues decreased, the change is KEPT. If not, DISCARDED.

## Guard

**Quality gate** = AntonCore Gate pass/fail. Even if issues decrease, the quality gate must still pass (no regressions on coverage, duplications, security rating).

## Scripts

| Script | Purpose | Autoresearch Field |
|--------|---------|-------------------|
| `sonar-scan.sh` | Rsync to Anton → docker scanner → extract metrics | `metric.command` |
| `sonar-gate.sh` | Check quality gate status (exit 0/1) | `guard.command` |
| `sonar-baseline.sh` | Get current issue count for new markers | Setup only |
| `sonar-onboard.sh` | Onboard a repo (detect patterns, generate config) | Setup only |

## Agent Profile

`agents/sonar-fixer/` — Claude Code agent tuned for single-issue fixes:
- Fix ONE issue per experiment
- No suppression comments
- No new dependencies
- Minimal, atomic changes

## Prerequisites

- `SONAR_ADMIN_TOKEN` env var set (SonarQube admin token, `squ_` prefix)
- SSH access to `root@10.10.30.130` via `~/.ssh/anton_id_ed25519`
- SonarQube running on Anton (`sonarqube_server` container on `anton_net`)
- Target repo has `sonar-project.properties`

## Usage

```bash
# Onboard a new repo
export SONAR_ADMIN_TOKEN="..."
bash harnesses/sonarqube/sonar-onboard.sh /path/to/repo project-key

# Track and run
autoresearch track /path/to/repo
autoresearch run repo-name:sonar-quality --max-experiments 5
```

## Onboarded Repos

| Repo | Project Key | Baseline |
|------|------------|----------|
| antoncore | `antoncore` | 202 (20 bugs, 0 vulns, 182 smells) |
