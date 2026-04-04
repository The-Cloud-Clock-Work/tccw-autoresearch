# Engine

> Experiment loop, escalation, commit/discard logic.

## Overview

The engine (`engine.py`) orchestrates the core improvement loop. It creates a worktree, runs experiments, measures metrics, and decides whether to keep or discard changes.

## Experiment Flow

1. **Setup** — Create git worktree for the marker's branch
2. **Read ideas** — Load previous ideas to avoid repeating failed strategies
3. **Generate program** — Synthesize a `program.md` with instructions for the agent
4. **Agent execution** — Claude Code agent edits mutable files based on the program
5. **Harness run** — Orchestrator executes the metric command on modified code
6. **Metric extraction** — Parse the single numeric result
7. **Guard check** — Run regression gate if configured
8. **Decision** — Orchestrator keeps (commit) or discards (reset)
9. **Record** — Append result to `results.tsv`
10. **Loop** — Repeat until budget exhausted

## Escalation Strategy

Consecutive failures trigger graduated responses:

| Threshold | Action |
|-----------|--------|
| `refine_after` (default: 3) | Refine approach, try variations |
| `pivot_after` (default: 5) | Pivot to a different strategy |
| `search_after_pivots` (default: 2) | Search for external solutions |
| `halt_after_pivots` (default: 3) | Halt with `needs_human` status |

## Commit/Discard Logic

- **Improved + guard passes** → `git commit` with descriptive message
- **Improved + guard fails** → Attempt rework (up to `rework_attempts`)
- **Not improved** → `git reset --hard`
- **Error in harness** → Discard, increment failure counter

## Lifecycle Hooks

The engine supports optional shell commands that run at specific points in the experiment loop. These are configured in the marker's `auto_merge` section and are completely generic — the engine runs them as `bash -c <command>` without knowing what they do.

### Hook Fields

| Field | Type | Default | When It Runs |
|-------|------|---------|--------------|
| `snapshot_command` | `str \| None` | `None` | **Before** each experiment, after the experiment counter increments but before the agent touches any code |
| `restore_command` | `str \| None` | `None` | **After** any experiment failure (crash, metric not improved, guard failed after rework) |

Both fields are optional. If omitted or `null`, the engine skips the hook entirely and behaves as before (git-only rollback).

### Contract

**`snapshot_command`:**
- Receives `{exp_num}` placeholder (replaced with the experiment number)
- **Last line of stdout = snapshot reference** (ID, path, tag — any string)
- The engine captures this and passes it to `restore_command` on failure
- Non-zero exit or timeout (120s) = warning logged, experiment proceeds without snapshot

**`restore_command`:**
- Receives `{snapshot_id}` placeholder (replaced with the value captured from `snapshot_command`)
- Runs **after** `git reset --hard` (code rollback), so it handles non-code state
- Non-zero exit or timeout (120s) = warning logged, engine continues
- If no snapshot was captured (snapshot_command failed or not configured), restore is skipped

### Flow Diagram

```
for each experiment:
    snapshot_ref = run(snapshot_command)     ← BEFORE agent
    agent edits code
    harness measures metric
    
    if FAIL (crash / metric / guard):
        git reset --hard                    ← code rollback
        run(restore_command, snapshot_ref)   ← infra rollback
        continue
    
    if KEEP:
        commit changes
        snapshot becomes stale (new known-good state)
```

### Examples

```yaml
# RESTIC backup (full service snapshot)
auto_merge:
  snapshot_command: "bash automation/backup-trigger.sh backup --stack myservice --tag exp-{exp_num}"
  restore_command: "bash automation/backup-trigger.sh restore --stack myservice --snapshot {snapshot_id}"

# Docker image tag
auto_merge:
  snapshot_command: "docker tag myapp:latest myapp:pre-exp-{exp_num} && echo pre-exp-{exp_num}"
  restore_command: "docker tag myapp:{snapshot_id} myapp:latest"

# Database dump
auto_merge:
  snapshot_command: "pg_dump -Fc mydb -f /tmp/pre-exp-{exp_num}.dump && echo /tmp/pre-exp-{exp_num}.dump"
  restore_command: "pg_restore -d mydb --clean {snapshot_id}"

# Helm values snapshot
auto_merge:
  snapshot_command: "helm get values myrelease -o yaml > /tmp/helm-{exp_num}.yaml && echo /tmp/helm-{exp_num}.yaml"
  restore_command: "helm upgrade myrelease mychart -f {snapshot_id}"

# No hooks (default — git-only rollback)
auto_merge:
  snapshot_command: null
  restore_command: null
```

### Error Handling

Hooks never crash the engine:
- Timeout: 120 seconds per hook call
- Failure: warning logged, experiment continues
- Missing snapshot: restore silently skipped (no snapshot_ref to pass)
- Both hooks are fire-and-forget from the engine's perspective

### What Hooks Do NOT Cover

- **Post-keep**: No hook after a successful experiment. The snapshot becomes stale; the new committed state is the known-good.
- **Post-merge**: The engine calls `_run_state_update()` (hardcoded to `automation/state-update.sh`), not a configurable hook.
- **Pre-merge**: No hook before `finalize_marker` / `merge_finalized`. The gate chain serves this role.
