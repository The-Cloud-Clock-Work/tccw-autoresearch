---
layout: default
title: Production Deployment
parent: Documentation Index
nav_order: 61
---

# 6B — Production Deployment Guide

## Overview

Step-by-step guide for deploying autoresearch on a real repo, based on the antoncore production deployment (2026-04-05). Covers every issue encountered and how it was resolved.

## Prerequisites

- `ruff` installed (`pip install ruff`)
- `gh` CLI authenticated (`gh auth status`)
- `claude` CLI authenticated (Claude Max OAuth token)
- Git repo with Python files
- Dev branch for auto-merge target

## Step 1: Create Marker Config

```yaml
# .autoresearch/config.yaml
markers:
  - name: lint-quality
    description: "Reduce ruff lint errors"
    status: active
    target:
      mutable:
        - "src/**/*.py"        # EVERY directory with Python files
        - "tests/**/*.py"
        - "scripts/**/*.py"
      immutable:
        - .autoresearch/config.yaml
    metric:
      command: "ruff check . 2>&1"
      extract: "grep -oP 'Found \\K\\d+'"
      direction: lower
      baseline: 0              # update after first ruff check
      target: 0
      issues_command: "ruff check . --output-format concise 2>&1 | head -30"
    guard:
      command: "ruff check . 2>&1 | grep -qP 'Found \\d+'"
      rework_attempts: 1
    agent:
      model: claude-sonnet-4-6  # sonnet for cost efficiency
      budget_per_experiment: 20m
      max_experiments: 1        # start with 1, increase when stable
    auto_merge:
      enabled: true
      target_branch: dev
    schedule:
      type: on-demand
```

## Step 2: Set Baseline

```bash
ruff check . 2>&1 | grep -oP 'Found \K\d+'
# Update baseline in config.yaml with this number
```

## Step 3: Verify Pipeline (Before Running)

```bash
# Metric works?
ruff check . 2>&1 | grep -oP 'Found \K\d+'

# Issues feed works?
ruff check . --output-format concise 2>&1 | head -10

# Guard works?
ruff check . 2>&1 | grep -qP 'Found \d+' && echo PASS || echo FAIL

# gh CLI works?
gh pr list --limit 1
```

ALL four must succeed before running.

## Step 4: Register and Run

```bash
autoresearch add --path /path/to/repo
autoresearch run --marker reponame:lint-quality
```

## Step 5: Verify Results

```bash
# Check GitHub for new PR
gh pr list --head autoresearch/

# Check metric dropped
ruff check . 2>&1 | grep -oP 'Found \K\d+'
```

## Common Issues (from Production)

### Agent makes zero edits

**Cause:** Files with issues are outside `target.mutable` paths.
**Fix:** Add all directories containing Python files to `mutable`.
**Detection:** `ruff check <dir>/ 2>&1 | head -5` for each mutable path.

### Metric doesn't change (stale baseline)

**Cause:** `state.json` has old `current_best` from a previous run.
**Fix:** `autoresearch add --path .` to re-register with fresh state.

### Agent times out without committing

**Cause:** Budget too short or agent explores too broadly.
**Fix:** `issues_command` gives exact targets. Engine always-commits on timeout. Budget countdown hook warns the agent.

### PR creation fails

**Cause:** `gh auth` not configured, or branch protection rules.
**Fix:** `gh auth login`, ensure dev branch allows direct pushes.

### Scanner infrastructure issues (SonarQube)

**Cause:** Remote scanner needs Java, Node.js, Docker, SSH, network routing.
**Fix:** Use `ruff` instead. Zero infrastructure. See `6A-HARNESS-RUFF.md`.

## Scaling

### More experiments per run

```yaml
agent:
  max_experiments: 10  # run 10 back-to-back
```

### Overnight schedule

```yaml
schedule:
  type: overnight  # runs at 1am daily
```

### Multiple repos

```bash
# Onboard each repo
for repo in agenticore agentibridge agentihooks; do
  cd /path/to/$repo
  # Create .autoresearch/config.yaml
  ruff check . 2>&1 | grep -oP 'Found \K\d+'  # baseline
  autoresearch add --path .
done

# Run all
autoresearch run --repo agenticore
autoresearch run --repo agentibridge
```
