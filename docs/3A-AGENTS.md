---
layout: default
title: Agents
parent: Documentation Index
nav_order: 30
---

# Agents

> Default agent, copilot agent, profile scaffolding.

## Overview

Agent profiles define how the AI agent behaves during experiments. Profiles are stored in `.autoresearch/agents/` and contain Claude Code configuration (CLAUDE.md, rules, commands, skills).

## Default Agent

Located at `.autoresearch/agents/default/`. Includes:

- `CLAUDE.md` — Agent identity and instructions
- `.claude/rules/autoresearch-agent.md` — Behavioral rules for the experiment loop
- `.claude/rules/git-discipline.md` — Git commit conventions
- `.claude/agents/researcher.md` — Researcher sub-agent definition
- `.claude/commands/run-metric.md` — Metric execution command
- `.claude/commands/check-coverage.md` — Coverage check command
- `.claude/skills/simplify-test/` — Test simplification skill

## Copilot Agent (planned)

A lighter-weight profile for assisted (non-autonomous) improvement. Configuration exists at `.autoresearch/agents/copilot/CLAUDE.md` but the profile is not yet fully implemented.

## Profile Loading

The `agent_profile.py` module handles loading and resolving agent profiles. Profiles from `.autoresearch/agents/` are scaffolded into the worktree at runtime.
