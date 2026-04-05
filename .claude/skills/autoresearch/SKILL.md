---
name: autoresearch
description: "Operate the autoresearch engine — run experiments, check status, review logs. Use when: 'run autoresearch', 'status', 'what experiments', 'check results', 'how is autoresearch doing'."
allowed-tools: Bash, Read, Glob, Grep
argument-hint: "[run|status|logs]"
---

# /autoresearch — Autonomous Improvement Engine

This project is **autoresearch** — an autonomous code improvement engine. It runs experiments:
edit code → measure a metric → keep if improved, discard if not → commit with audit trail.
Any metric, any language, any repo. The `.autoresearch/config.yaml` marker defines what to measure.

**Invocation:** `/autoresearch [subcommand]`

| Subcommand | What it does | Modifies state? |
|------------|-------------|-----------------|
| `run` | Register marker + run experiment(s) locally | Yes |
| `status` | Dashboard: marker config, state, last results | No |
| `logs` | Experiment history, kept commits, log files | No |

If no subcommand given, default to `status`.

---

## Subcommand: `run`

Step 1 — Detect marker from config:
```bash
REPO_ROOT="$(git rev-parse --show-toplevel)"
MARKER_NAME=$(grep -m1 '^\s*- name:' "${REPO_ROOT}/.autoresearch/config.yaml" 2>/dev/null | sed 's/.*name:\s*//')
REPO_NAME=$(basename "$REPO_ROOT")
```

Step 2 — Register marker (idempotent):
```bash
autoresearch add --path "$REPO_ROOT"
```

Step 3 — Run experiment loop:
```bash
cd "$REPO_ROOT" && autoresearch run --marker "${REPO_NAME}:${MARKER_NAME}"
```

**AI-JUDGMENT:** Stream output. When complete, summarize:
- Experiments ran, kept vs discarded
- Final metric value
- Whether HALT fired
- Next action suggestion

---

## Subcommand: `status`

<!-- DETERMINISTIC: Collect marker status and results -->
```bash
bash .claude/skills/autoresearch/scripts/10_marker_status.sh
```

**AI-JUDGMENT:** Format as a dashboard:

```
AUTORESEARCH STATUS
════════════════════════════════════════════════

◼ MARKER: <repo>:<marker>
  Status:          <active/paused/needs_human>
  Last run:        <timestamp or never>
  Experiments:     <total>  Kept: <n>  Discarded: <n>
  Metric baseline: <baseline>
  Current metric:  <current or unmeasured>
  Direction:       <lower/higher>
  Budget:          <budget per experiment>

◼ CONFIG
  Mutable:    <paths>
  Immutable:  <paths>
  Metric cmd: <command>
  Guard cmd:  <command>
  Auto-merge: <enabled/disabled> → <target_branch>

◼ RESULTS (last experiments)
  COMMIT     METRIC  GUARD  STATUS     DESCRIPTION
  <rows from results.tsv>
```

Flag actionable items:
- No results yet → suggest `/autoresearch run`
- All discarded → metric or agent may be stuck
- Marker not registered → run `autoresearch add` first
- Config missing → run `autoresearch init` first

---

## Subcommand: `logs`

<!-- DETERMINISTIC: Parse results and log evidence -->
```bash
bash .claude/skills/autoresearch/scripts/40_logs_summary.sh
```

**AI-JUDGMENT:** Format results.tsv as readable table. Interpret:
- Which experiments kept vs discarded — pattern analysis
- Files modified (from git log)
- Metric trending down/up (good depends on direction) or flat (stuck)
- Log files: summarize last experiment's agent output if available
- Suggested next action

---

## Rules

- **Auto-detect everything:** Marker name, repo name, paths — all from `.autoresearch/config.yaml` and git. Never hardcode.
- **Deterministic:** Run scripts exactly as shown. Do not inline script contents.
- **Graceful degradation:** `ERROR:` in output → show UNAVAILABLE, continue with other sections.
- **Read-only except `run`:** `status` and `logs` never modify anything.
- **Local only:** No SSH, no remote APIs, no GitHub Actions. Everything from local files.

## Scripts

| Script | Purpose |
|--------|---------|
| `10_marker_status.sh` | Marker config + state.json + results.tsv |
| `40_logs_summary.sh` | Results + git log + agent log files |
