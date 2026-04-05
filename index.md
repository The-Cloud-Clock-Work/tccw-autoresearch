---
layout: home
title: Home
nav_order: 1
description: "AutoResearch — Agnostic autonomous improvement engine."
permalink: /
---

# AutoResearch
{: .fs-9 .fw-700 }

Point it at any codebase — it makes it measurably better overnight while you sleep.
{: .fs-5 .text-grey-dk-100 .mb-6 }

<div class="hero-actions text-center mb-8" markdown="0">
  <a href="#quick-start" class="btn btn-primary fs-5 mr-2">Quick Start</a>
  <a href="{{ site.baseurl }}/docs/0A-ARCHITECTURE/" class="btn btn-green fs-5 mr-2">Architecture</a>
  <a href="https://pypi.org/project/tccw-autoresearch/" class="btn fs-5 mr-2" target="_blank">PyPI</a>
  <a href="https://github.com/The-Cloud-Clock-Work/tccw-autoresearch" class="btn fs-5" target="_blank">GitHub</a>
</div>

---

## What It Does

```
LOOP:
  1. Edit target files (Claude Code agent)
  2. Run immutable harness (your metric command)
  3. Measure single metric (extract a number)
  4. If improved → keep (git commit)
  5. If worse   → discard (git reset)
  6. REPEAT until budget exhausted
```

Works on anything with a measurable outcome: lint errors, test pass rates, build times, coverage percentages, response latency. **No GPU. No ML. Tests replace training runs.**

---

## Quick Start
{: #quick-start }

```bash
pip install tccw-autoresearch
cd your-project
autoresearch init
```

Claude opens interactively, scans your project, asks what to improve, configures the marker, measures baseline. Three commands from zero to running.

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
    loop:
      budget_per_experiment: 20m
      max_experiments: 10
```

The engine creates a git worktree, spawns a Claude Code agent, measures before/after, keeps improvements, discards regressions. Every kept experiment is a commit with full audit trail.

---

## Key Features

| Feature | Description |
|---------|-------------|
| **Any metric** | Shell command → extract number → direction. That's it. |
| **Agent profiles** | Default agent ships with the package. Duplicate to customize. |
| **Budget countdown** | Agent sees remaining time after every tool call. |
| **Auto-merge** | Kept experiments → PR to dev → promotion PR to main. |
| **Graduated escalation** | 3 fails → refine → 5 → pivot → search → halt |
| **Statistical confidence** | MAD-based scoring after 3+ experiments |
| **Claude Code skills** | `/onboard` wizard + `/autoresearch` status/logs |
| **Dual-mode CLI** | Interactive TUI + headless JSON (`--headless`) |

---

## Documentation

| Section | Topics |
|---------|--------|
| [Architecture]({{ site.baseurl }}/docs/0A-ARCHITECTURE/) | Core loop, design principles |
| [Marker Config]({{ site.baseurl }}/docs/1A-MARKER/) | Schema, states, lifecycle |
| [Engine]({{ site.baseurl }}/docs/1B-ENGINE/) | Experiment loop, escalation |
| [CLI]({{ site.baseurl }}/docs/2A-CLI/) | 13 commands, interactive + headless |
| [Agents]({{ site.baseurl }}/docs/3A-AGENTS/) | Default agent, custom profiles |
| [Gates]({{ site.baseurl }}/docs/1E-GATES/) | Gate chain, auto-publish PRs |
| [Production]({{ site.baseurl }}/docs/6B-PRODUCTION-DEPLOYMENT/) | Step-by-step deployment |
