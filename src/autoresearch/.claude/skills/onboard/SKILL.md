---
name: onboard
model: opus
description: >
  Set up autoresearch on any repo. Interactive Q&A to create a marker config.
  Use when: "onboard", "set up autoresearch", "add marker", "install autoresearch",
  "configure autoresearch", "onboard a repo", "add autoresearch to a project".
argument-hint: "[repo-path]"
---

# onboard — Set up autoresearch on any repository

Guides the user through an interactive Q&A to install autoresearch on a target repo,
configure a marker, and optionally run a first experiment.

## Script Resolution

```bash
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-}")" && pwd)"
if [[ ! -d "$SKILL_DIR/scripts" ]]; then
  SKILL_DIR="$(dirname "$(readlink -f .claude/skills/onboard/SKILL.md)" 2>/dev/null || echo ".claude/skills/onboard")"
fi
```

---

## Step 1: Get Target Repo Path (AI-JUDGMENT)

If the user provided a repo path as an argument, use it. Otherwise, ask:

Use AskUserQuestion:
- "Which repository do you want to set up autoresearch on?"
- Options: "Current directory" (CWD), "Enter a path" (Other)

---

## Step 2: Validate Target Repo

<!-- DETERMINISTIC: validate the target path is a git repo with recognizable structure -->
```bash
"$SKILL_DIR"/scripts/01_validate_repo.sh <repo-path>
```

If validation fails, tell the user why and ask for a different path.

---

## Step 3: Check Prerequisites

<!-- DETERMINISTIC: verify autoresearch and claude CLIs are available -->
```bash
"$SKILL_DIR"/scripts/02_check_prerequisites.sh
```

If either is missing, show the error message from the script and do NOT proceed until both are available.

---

## Step 4: Run `autoresearch init`

<!-- DETERMINISTIC: scaffold .autoresearch/ in the target repo -->
```bash
"$SKILL_DIR"/scripts/03_run_init.sh <repo-path>
```

If the script outputs `EXISTS:`, inform the user that `.autoresearch/config.yaml` already exists and ask whether to add a new marker or reconfigure.

---

## Step 5: Scan the Target Repo (AI-JUDGMENT)

Before asking questions, scan the repo to provide informed suggestions:

1. **List top-level structure** — `ls` the repo, identify key directories
2. **Detect tech stack** — check for package.json, pyproject.toml, Cargo.toml, go.mod, Makefile, etc.
3. **Find existing tests** — look for `tests/`, `test/`, `spec/`, `__tests__/`, `*_test.go`, etc.
4. **Check for CI** — `.github/workflows/`, `.gitlab-ci.yml`, etc.
5. **Check for lint config** — `.ruff.toml`, `.eslintrc`, `.flake8`, `rustfmt.toml`, etc.

Use this information to provide smart defaults in the following questions.

---

## Step 6: Ask What to Improve (AI-JUDGMENT)

Use AskUserQuestion to ask what the user wants to improve. Offer suggestions based on what you found in Step 5:

Typical options (only show what's relevant to the detected stack):
- **Test pass count** — increase the number of passing tests
- **Code coverage** — increase test coverage percentage
- **Build time** — reduce build/compile time
- **Lint warnings** — reduce linter errors/warnings
- **Custom** — user describes their own metric

Explain each option briefly so the user understands what the engine will optimize for.

---

## Step 7: Ask Mutable Files (AI-JUDGMENT)

Use AskUserQuestion to ask which files the agent should be allowed to edit.

Based on the scan, suggest glob patterns. For example:
- If improving tests: `tests/**/*.py` (test files are mutable, source is immutable)
- If improving source quality: `src/**/*.py` (source is mutable, tests are immutable)
- If reducing lint: `src/**/*.py`

Explain: "Mutable files are the ones the AI agent will edit to try improvements. Immutable files are the harness — they define what 'better' means and are never touched."

---

## Step 8: Ask Immutable Files (AI-JUDGMENT)

Use AskUserQuestion to ask which files should never be touched.

Suggest based on the improvement goal:
- If mutable is tests → immutable is source (`src/**/*.py`)
- If mutable is source → immutable is tests (`tests/**/*.py`)

Explain: "These are your test/harness files. The agent runs them to measure improvement but never modifies them."

---

## Step 9: Guide Metric Selection (AI-JUDGMENT)

Based on the improvement goal from Step 6, suggest a metric command + extract pair.

### Common Metric Templates

| Goal | Tech | `metric.command` | `metric.extract` | `direction` |
|------|------|-------------------|-------------------|-------------|
| Test pass count | Python/pytest | `pytest tests/ -q --tb=no 2>&1 \| tail -1` | `grep -oP '\\d+(?= passed)'` | higher |
| Test pass count | Node/jest | `npx jest --silent 2>&1 \| tail -3` | `grep -oP '\\d+(?= passed)'` | higher |
| Test pass count | Go | `go test ./... 2>&1 \| tail -1` | `grep -oP '(?:ok\\s+)\\d+'` | higher |
| Test pass count | Rust | `cargo test 2>&1 \| grep 'test result'` | `grep -oP '\\d+(?= passed)'` | higher |
| Coverage % | Python/pytest | `pytest --cov=src --cov-report=term 2>&1 \| tail -1` | `grep -oP '\\d+(?=%)'` | higher |
| Coverage % | Node/jest | `npx jest --coverage --silent 2>&1 \| grep 'All files'` | `grep -oP '\\d+\\.?\\d*' \| head -1` | higher |
| Build time (s) | Make | `bash -c 'TIMEFORMAT=%R; time make build 2>&1'` | `tail -1` | lower |
| Build time (s) | npm | `bash -c 'TIMEFORMAT=%R; time npm run build 2>&1'` | `tail -1` | lower |
| Lint warnings | Python/ruff | `ruff check src/ 2>&1 \| tail -1` | `grep -oP '\\d+(?= error)'` | lower |
| Lint warnings | Node/eslint | `npx eslint src/ 2>&1 \| tail -1` | `grep -oP '\\d+(?= problem)'` | lower |

Present the suggested metric to the user. Explain what the command does and what the extract pulls out. Let them confirm or customize.

**Important:** Offer to run the metric command right now to establish the baseline value. If the user agrees, use the baseline measurement script in Step 12.

---

## Step 10: Ask Loop Config (AI-JUDGMENT)

Use AskUserQuestion for loop settings with sensible defaults:

- **Model**: sonnet (recommended), opus (more capable, higher cost), haiku (fast, cheaper)
- **Budget per experiment**: 10m (default), 5m (quick), 25m (complex)
- **Max experiments**: 20 (default)

Most users should accept defaults. Explain briefly what each means.

---

## Step 11: Generate Marker YAML (AI-JUDGMENT)

Assemble all answers into a valid marker config. Write it to `<repo-path>/.autoresearch/config.yaml`.

If the config already has markers, append the new one to the existing `markers:` list.

Show the generated YAML to the user before writing. Ask for confirmation.

---

## Step 12: Measure Baseline

<!-- DETERMINISTIC: run the metric command and extract the baseline value -->
```bash
"$SKILL_DIR"/scripts/04_measure_baseline.sh <repo-path> "<metric-command>" "<extract-command>"
```

Update `metric.baseline` in the config with the measured value.

---

## Step 13: Summary & Next Steps (AI-JUDGMENT)

Show the user:

```
## Autoresearch Configured

**Repo:** <repo-path>
**Marker:** <marker-name>
**Goal:** <improvement goal>
**Metric:** <direction> is better
**Baseline:** <measured value>
**Budget:** <max_experiments> experiments × <budget_per_experiment> each

## How to Run

  # Interactive
  cd <repo-path> && autoresearch

  # Headless (AI agents, CI/CD, cron)
  cd <repo-path> && autoresearch run -m <marker-name> --headless

  # Check progress
  autoresearch status -m <marker-name> --headless
  autoresearch results -m <marker-name> --headless
```

Ask: "Want to run a first experiment now?"

---

## When NOT to Use

- The repo already has a fully configured `.autoresearch/config.yaml` with active markers
- The user just wants to run an existing marker (use `autoresearch run` directly)
- The user wants to edit an existing marker (edit the YAML directly)

---

## Extracted Scripts

| Script | Purpose | Idempotent |
|--------|---------|-----------|
| `01_validate_repo.sh` | Validate target path is a git repo with recognizable structure | Yes |
| `02_check_prerequisites.sh` | Verify `autoresearch` and `claude` CLIs are on PATH | Yes |
| `03_run_init.sh` | Run `autoresearch init --headless` in the target repo | Yes (skips if config exists) |
| `04_measure_baseline.sh` | Run metric command and extract baseline number | Yes |
