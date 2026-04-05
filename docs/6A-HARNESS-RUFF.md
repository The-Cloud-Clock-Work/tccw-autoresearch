# 6A — Ruff Harness (Production Reference)

## Overview

The first production-validated harness for autoresearch. Uses `ruff` (Python linter) as the deterministic metric. Zero infrastructure — runs in 2 seconds from any repo with Python files.

## Why Ruff (Not SonarQube)

SonarQube was the original metric choice. It failed in production due to:

| Issue | Impact |
|-------|--------|
| Scanner Docker image (Alpine) has no Node.js | JS-in-HTML analysis crashes, throws away Python results |
| Scanner v8.0.1 uses v2 API | Incompatible with SonarQube CE |
| Scanner v5.0.1 can't run without Java | WSL2/containers don't have Java |
| 5+ minute scan cycle (rsync → Docker → poll) | Too slow for experiment loops |
| Network routing issues on Unraid | Containers can't reach SonarQube |

Ruff solves all of these: `pip install ruff`, runs in 2 seconds, 800+ Python rules, zero dependencies.

## Configuration

```yaml
# .autoresearch/config.yaml
markers:
  - name: sonar-quality
    description: "Reduce ruff lint errors across Python codebase"
    target:
      mutable:
        - "automation/**/*.py"
        - "stacks/**/*.py"
        - "packages/**/*.py"
        - "tests/**/*.py"
        - "agents/**/*.py"
        - "cli/**/*.py"
      immutable:
        - .autoresearch/config.yaml
    metric:
      command: "ruff check . 2>&1"
      extract: "grep -oP 'Found \\K\\d+'"
      direction: lower
      baseline: 163
      target: 0
      issues_command: "ruff check . --output-format concise 2>&1 | head -30"
    guard:
      command: "ruff check . 2>&1 | grep -qP 'Found \\d+'"
      rework_attempts: 1
    loop:
      budget_per_experiment: 20m
      max_experiments: 1
```

## Key Fields

### `metric.command` + `metric.extract`

```bash
$ ruff check . 2>&1
# ... individual errors ...
# Found 163 errors.
# [*] 120 fixable with the `--fix` option.

$ ruff check . 2>&1 | grep -oP 'Found \K\d+'
163
```

### `metric.issues_command`

This is injected into the agent's prompt as exact `file:line:rule` issues:

```bash
$ ruff check . --output-format concise 2>&1 | head -30
agents/anton/recommendation/agent.py:19:47: F401 [*] `prompt.DEFAULT_SYSTEM_PROMPT` imported but unused
packages/litellm_manager/litellm_manager/cli.py:7:1: E402 Module level import not at top of file
packages/litellm_manager/litellm_manager/commands/keys.py:63:16: F541 [*] f-string without any placeholders
```

The agent gets EXACT targets — no exploration needed. This is the single biggest improvement to experiment success rate.

### `guard.command`

The guard just confirms ruff runs without crashing (the code is valid Python). The metric itself is the real validation.

## Production Results (antoncore, 2026-04-05)

| Run | Baseline | Result | Delta | Status |
|-----|----------|--------|-------|--------|
| 1 | 186 | 163 | -23 | KEEP |
| 2 | 163 | 133 | -30 | KEEP |

**Total: 186 → 133 in 2 experiments. -53 errors. PRs: #218 (merged), #219 (pending approval).**

## Lessons Learned

1. **Issues command is critical** — without it, the agent spends 15 minutes exploring. With it, fixes are surgical and fast.
2. **Mutable paths must cover all directories with issues** — agent silently skips files outside mutable list.
3. **Baseline must match current state** — stale baseline in state.json causes "no improvement" false discards.
4. **Guard should be trivial** — complex test suites with missing deps fail the guard. Ruff-as-guard is simple and reliable.
5. **Always-commit in engine** — agent may timeout before committing. Engine does `git add -A && commit` regardless of agent success/failure.

## Applying to Other Repos

```bash
# Any Python repo:
cat > .autoresearch/config.yaml << 'EOF'
markers:
  - name: lint-quality
    target:
      mutable: ["src/**/*.py", "tests/**/*.py"]
      immutable: [.autoresearch/config.yaml]
    metric:
      command: "ruff check . 2>&1"
      extract: "grep -oP 'Found \\K\\d+'"
      direction: lower
      baseline: 0  # will be set by first scan
      issues_command: "ruff check . --output-format concise 2>&1 | head -30"
    guard:
      command: "ruff check . 2>&1 | grep -qP 'Found \\d+'"
    loop:
      model: sonnet
      budget_per_experiment: 20m
      max_experiments: 5
EOF

# Get baseline
ruff check . 2>&1 | grep -oP 'Found \K\d+'
# Update baseline in config.yaml

# Register and run
autoresearch add --path .
autoresearch run --marker <repo>:lint-quality
```
