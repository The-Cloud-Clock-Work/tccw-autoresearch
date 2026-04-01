# Engine

> Experiment loop, escalation, commit/discard logic.

## Overview

The engine (`engine.py`) orchestrates the core improvement loop. It creates a worktree, runs experiments, measures metrics, and decides whether to keep or discard changes.

## Experiment Flow

1. **Setup** — Create git worktree for the marker's branch
2. **Idea generation** — AI agent proposes an improvement
3. **Program synthesis** — Generate concrete code changes
4. **Harness run** — Execute the metric command on modified code
5. **Metric extraction** — Parse the single numeric result
6. **Guard check** — Run regression gate if configured
7. **Decision** — Keep (commit) if improved and guard passes, discard (reset) otherwise
8. **Record** — Append result to `results.tsv`
9. **Loop** — Repeat until budget exhausted

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
