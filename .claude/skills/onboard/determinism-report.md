# Determinism Report — onboard skill

**Target:** `.claude/skills/onboard/SKILL.md`
**Date:** 2026-04-01

## Classification

| Step | Type | Reasoning |
|------|------|-----------|
| 1. Get Target Repo Path | AI-JUDGMENT | Interprets user input, uses AskUserQuestion |
| 2. Validate Target Repo | DETERMINISTIC | Fixed validation logic → `01_validate_repo.sh` |
| 3. Check Prerequisites | DETERMINISTIC | Fixed `command -v` checks → `02_check_prerequisites.sh` |
| 4. Run autoresearch init | DETERMINISTIC | Fixed CLI command → `03_run_init.sh` |
| 5. Scan Target Repo | AI-JUDGMENT | Requires interpreting repo structure for contextual suggestions |
| 6. Ask What to Improve | AI-JUDGMENT | Interactive Q&A with contextual options |
| 7. Ask Mutable Files | AI-JUDGMENT | Contextual glob pattern suggestions |
| 8. Ask Immutable Files | AI-JUDGMENT | Contextual suggestions based on goal |
| 9. Guide Metric Selection | AI-JUDGMENT | Template selection + contextual explanation |
| 10. Ask Loop Config | AI-JUDGMENT | Interactive Q&A with defaults |
| 11. Generate Marker YAML | AI-JUDGMENT | Assembles variable answers into config |
| 12. Measure Baseline | DETERMINISTIC | Fixed shell execution → `04_measure_baseline.sh` |
| 13. Summary & Next Steps | AI-JUDGMENT | Contextual output with user interaction |

## Summary

| Metric | Value |
|--------|-------|
| Total steps | 13 |
| DETERMINISTIC | 4 (31%) |
| AI-JUDGMENT | 9 (69%) |
| Scripts created | 3 new + 1 existing |
| Backup | `SKILL.md.pre-enforce-deter.bak` |

## Advisory

This workflow is appropriately AI-heavy — it is an interactive Q&A skill where the AI must interpret user context, scan a repo, and make contextual suggestions. The 4 deterministic steps (validate, prerequisites, init, baseline) are the natural extraction points.

## Scripts Created

| Script | Purpose |
|--------|---------|
| `scripts/01_validate_repo.sh` | Validate target is a git repo (pre-existing) |
| `scripts/02_check_prerequisites.sh` | Verify `autoresearch` + `claude` on PATH |
| `scripts/03_run_init.sh` | Run `autoresearch init --headless` (idempotent) |
| `scripts/04_measure_baseline.sh` | Execute metric command and extract baseline |
