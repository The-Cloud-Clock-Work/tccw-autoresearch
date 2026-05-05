# TCC-AutoResearch Vision

> **Author:** Nestor Colt
> **Date:** 2026-03-30
> **Status:** Living document -- operator-owned, iterated by hand
> **Lineage:** Inspired by [karpathy/autoresearch](https://github.com/karpathy/autoresearch) -- methodology only, zero code dependency

---

## What This Is

An **agnostic, self-contained autonomous improvement engine**. Point it at any codebase, any file, any module -- it will make it measurably better overnight while you sleep.

This is not an Anton feature. This is not an OpenClaw integration. This is a standalone system that happens to be built by the same operator, and will be tested against Anton targets first because that's what's available. But the engine knows nothing about Anton, Kubernetes, MCP servers, or any specific stack. It knows: files, metrics, git, and loops.

---

## The Core Idea

Karpathy proved the pattern with ML training: an AI agent edits code, runs a fixed evaluation, keeps improvements, discards regressions, and never stops. His implementation is locked to GPU training (`train.py`, `val_bpb`, PyTorch). The insight is universal.

**Strip the ML. Keep the loop.**

```
LOOP:
  1. Edit target files
  2. Run immutable harness
  3. Measure single metric
  4. If improved --> keep (git commit)
  5. If worse --> discard (git reset)
  6. REPEAT until budget exhausted
```

This works on anything with a measurable outcome: test pass rates, build times, response latency, error counts, coverage percentages, smoke test scores. No GPU required. Tests replace training runs. Existing CI/CD infrastructure is the compute.

---

## The AutoResearch Marker

The central concept is the **marker**. A marker is a declaration: "this thing is under autonomous improvement."

A `.autoresearch/config.yaml` file in any repository declares one or more markers. Each marker defines what to improve, how to measure it, and what constraints apply. When the engine finds a marker, it knows exactly what to do.

You look at your repos and instantly see what's being improved. You add a marker, the engine picks it up. You set a marker to `skip`, the engine ignores it. You set it to `active`, it runs overnight. The marker is the interface between human intent and autonomous execution.

Multiple markers per repo. Each independent. Each on its own git worktree. Each with its own branch, results, and history. Parallel improvement loops that never collide.

---

## The Repo Is the Engine

The most important architectural decision: **the repo is self-contained**. The `.autoresearch/config.yaml` marker file carries everything needed to run the improvement loop. The CLI reads it from the repo, generates agent instructions at runtime, executes the loop right there in the worktree. No external payloads, no config transfer, no special integrations.

This means execution is trivially portable. Any system that can clone the repo and run `autoresearch run -m <marker> --headless` can execute markers. The CLI is the universal interface -- the same command for a human at their terminal, an AI agent in a pipeline, a CI/CD step, or a remote execution engine.

```
# Human at terminal
autoresearch run -m auth-flow

# AI agent (agenticore, GitHub Actions, any runner)
autoresearch run -m auth-flow --headless

# Remote via SSH
ssh server "cd repo && autoresearch run -m auth-flow --headless"
```

No adapters. No plugins. No executor abstraction layer. Just the CLI, the repo, and the marker file. If the `autoresearch` CLI is installed in the environment, it works.

---

## Three Interfaces, One Engine

**Interactive CLI** -- for the operator. Dynamic menus, selectable options, status at a glance. Run from home directory to see everything. Run from a repo directory to see its markers. Select a marker, press `r`, it runs. Didactic, visual, fast.

**Headless mode** -- for AI agents and scripts. Same functionality, zero interactivity. All inputs via flags. JSON output. Documented for autonomous consumption. An AI agent can discover markers, set them, run them, read results -- all through the CLI without a human in the loop.

Every feature has both modes. No exceptions. The `/enhance-cli` skill enforces this pattern.

**Daemon** -- a persistent local process that watches tracked repos and runs scheduled markers. Start it, forget it. It reads `~/.autoresearch/` for state and config, executes loops on schedule, reports results.

---

## Deferred Execution (No Special Integration)

Because the repo is self-contained and the CLI is the universal interface, deferred execution is free. You don't need a special adapter or payload format to run markers remotely:

- **Agenticore** -- `run_task(repo_url=..., task="autoresearch run -m auth-flow --headless")`. Agenticore clones the repo, the CLI reads the marker from the repo, runs the loop. Agenticore doesn't need to understand autoresearch internals.
- **GitHub Actions** -- `run: autoresearch run -m auth-flow --headless` in a workflow step. Same thing.
- **Cron on any machine** -- `0 1 * * * cd /path/to/repo && autoresearch run -m auth-flow --headless`

The only prerequisite: the `autoresearch` CLI must be available in the execution environment (`pip install tcc-autoresearch` or pre-installed in the container image).

This is intentional. No integration layer means no integration maintenance. Any future execution backend works automatically as long as it can run a shell command in a repo.

---

## What Success Looks Like

1. I write a `.autoresearch/config.yaml` in any repo with a marker targeting flaky code
2. I run `autoresearch` from my terminal, see the marker, press `r`
3. The engine creates a worktree, loops overnight, runs 50-100 experiments
4. I wake up to `results.tsv` showing the progression and a branch with the winning code
5. I review, merge, done

Or: an AI agent detects a degradation, writes a `.autoresearch/config.yaml` marker, triggers the engine via `--headless`, and resolves the issue before I even notice. That's the end state.

Or: I dispatch markers to agenticore overnight with a single headless command. No special payload, no custom integration. Agenticore just runs the CLI in the repo like any other task.

---

## Smarter Than a Dumb Loop

The basic loop (edit→test→keep/discard) is the foundation. But a dumb loop forgets what it tried, doesn't know if improvements are real, can't recover from being stuck, and leaves a mess when it's done. Five capabilities make the loop intelligent:

**Ideas Backlog + Failure Memory** -- when an experiment is discarded, the agent writes WHY the direction was interesting and what conditions might make it viable. Stored in `.autoresearch/<marker>/ideas.md`. Future sessions read this before generating hypotheses. The loop compounds knowledge across sessions instead of re-trying failed approaches.

**Graduated Failure Escalation** -- instead of "crash 3 times and stop," the engine escalates:
- 3 consecutive failures → REFINE (adjust strategy within current approach)
- 5 consecutive failures → PIVOT (abandon approach, try new direction)
- 2 PIVOTs without progress → SEARCH (external web search for ideas)
- 3 PIVOTs total → HALT with `needs_human` status

**Statistical Confidence Scoring** -- after 3+ experiments, compute confidence to distinguish real improvements from benchmark noise. A metric going 24→25 might be noise; 24→31 is real. Prevents keeping changes that are just variance.

**Guard Command (Dual-Gate Verification)** -- separate the improvement metric from a regression guard. Gate 1: "did the metric improve?" Gate 2: "did anything else break?" Metric improves but guard fails → rework (2 attempts), then discard. Prevents gaming the metric by breaking something else.

**Finalization Workflow** -- after the loop completes, the experimental branch is messy. `autoresearch finalize <marker>` transforms it into clean, reviewable branches grouped by logical change. Separates exploration history from production-ready code.

---

## Design Principles

- **Agnostic** -- no assumptions about what it improves. Infra code, application code, configs, agent instructions, Dockerfiles, Helm charts -- anything with a metric
- **Config-driven** -- all behavior defined in YAML. No hardcoded targets, no magic
- **Safe** -- immutable harness never edited. Git worktree isolation. Dual-gate verification. Operator approves merges
- **Observable** -- results.tsv, confidence scores, ideas backlog, status dashboard
- **Composable** -- multiple independent loops run in parallel on different branches
- **Dual-mode** -- every CLI feature works interactively AND headlessly
- **Learns** -- failure memory, ideas backlog, statistical validation. The loop gets smarter over time

---

## What This Is NOT

- Not a CI/CD system -- it improves code, not deploys it
- Not a testing framework -- it uses existing tests as harness
- Not tied to any LLM provider -- agent invocation is pluggable
- Not a fork of karpathy/autoresearch -- clean-room implementation of the methodology
- Not a multi-agent orchestrator -- one loop, one agent, one metric, one target

---

## Pilot Targets (for validation, not scope)

These are the first things we'll point the engine at to prove it works. They happen to be in antoncore because that's what exists. The engine doesn't know or care.

1. **cc_auth_fixer agent** -- 34 smoke tests as harness, pass rate as metric
2. **"Create Tracker" pipeline** -- steps completed (0-5) as metric
3. **MCP onboarding skill** -- completion steps as metric

---

## Cost Model

| Resource | Per Experiment | 100 Experiments (Overnight) |
|----------|---------------|-----------------------------|
| Sonnet | ~$0.03-0.10 | $3-10 |
| Opus | ~$0.15-0.50 | $15-50 |
| Compute | Free (tests on existing infra) | Free |

---

## Open Questions (to be resolved during build)

- How exactly is the LLM agent invoked? (Claude Code `-p`? Agent SDK? Pluggable?)
- Notification system -- agnostic plugins or hardcoded channels?
- Discovery agent -- auto-propose markers for new targets?
- Merge workflow -- manual, CLI command, or auto-PR?
- Cost tracking across markers
- Multi-repo coordination in a single daemon run
- CLI packaging and distribution (PyPI? Single binary? Container image for remote envs?)
