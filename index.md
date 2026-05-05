---
layout: home
title: Home
nav_order: 1
description: "AutoResearch — A Claude Code wrapper that makes any codebase measurably better overnight."
permalink: /
---

# AutoResearch
{: .fs-9 .fw-700 }

A Claude Code wrapper that makes any codebase measurably better overnight.
{: .fs-5 .text-grey-dk-100 .mb-6 }

<div class="hero-actions text-center mb-8" markdown="0">
  <a href="#quick-start" class="btn btn-primary fs-5 mr-2">Quick Start</a>
  <a href="{{ site.baseurl }}/docs/0A-ARCHITECTURE/" class="btn btn-green fs-5 mr-2">Architecture</a>
  <a href="https://pypi.org/project/tcc-autoresearch/" class="btn fs-5 mr-2" target="_blank">PyPI</a>
  <a href="https://github.com/The-Cloud-Clockwork/tcc-autoresearch" class="btn fs-5" target="_blank">GitHub</a>
</div>

---

## What Is This?

AutoResearch is an orchestrator built on top of [Claude Code](https://docs.anthropic.com/en/docs/claude-code). You define a metric. Claude does the coding. AutoResearch decides what to keep.

```
autoresearch (orchestrator)
  └── claude (the brain)
        ├── reads your code
        ├── forms a hypothesis
        ├── edits files
        ├── runs your metric
        └── commits if improved, reverts if not
```

Reduce lint errors. Increase test coverage. Cut build times. Fix code smells. **Anything you can measure with a shell command.**

---

## Quick Start
{: #quick-start }

```bash
pip install tcc-autoresearch
cd your-project
autoresearch init
```

Claude opens interactively, scans your project, asks what to improve, configures the marker, measures baseline. **Three commands from zero to running.**

**Prerequisites:** Python 3.10+ and [Claude Code](https://docs.anthropic.com/en/docs/claude-code) installed.

---

## How It Works

The `.autoresearch/config.yaml` marker declares what to improve:

```yaml
markers:
  - name: lint-quality
    metric:
      command: "ruff check src/ 2>&1"
      extract: "grep -oP 'Found \\K\\d+'"
      direction: lower
      baseline: 163
    target:
      mutable: ["src/**/*.py"]
      immutable: ["tests/**/*.py"]
    agent:
      budget_per_experiment: 20m
      max_experiments: 10
```

The engine creates a git worktree, spawns a Claude Code agent, measures before/after, keeps improvements, discards regressions. Every kept experiment is a commit with full audit trail.

---

## Production Results

Deployed on antoncore (3.3k LOC Python monorepo):

| Cycle | Before | After | Delta |
|-------|--------|-------|-------|
| 1 | 186 errors | 163 | -23 |
| 2 | 163 | 133 | -30 |
| 3 | 133 | 0 | -133 |

**186 → 0 ruff errors in 3 cycles.** Full GitHub PR audit trail.

---

## Documentation

| Section | Topics |
|---------|--------|
| [Architecture]({{ site.baseurl }}/docs/0A-ARCHITECTURE/) | Core loop, design principles |
| [Marker Config]({{ site.baseurl }}/docs/1A-MARKER/) | Schema, states, lifecycle |
| [Engine]({{ site.baseurl }}/docs/1B-ENGINE/) | Experiment loop, escalation |
| [CLI]({{ site.baseurl }}/docs/2A-CLI/) | 13 commands, interactive + headless |
| [Agents]({{ site.baseurl }}/docs/3A-AGENTS/) | Default agent, custom profiles |
| [Budget Countdown]({{ site.baseurl }}/docs/3C-BUDGET-COUNTDOWN/) | PostToolUse time awareness |
| [Gates]({{ site.baseurl }}/docs/1E-GATES/) | Gate chain, auto-publish PRs |
| [Ruff Harness]({{ site.baseurl }}/docs/6A-HARNESS-RUFF/) | Production reference |
| [Production Deployment]({{ site.baseurl }}/docs/6B-PRODUCTION-DEPLOYMENT/) | Step-by-step guide |
