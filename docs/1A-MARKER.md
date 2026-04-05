---
layout: default
title: Marker Config
parent: Documentation Index
nav_order: 10
---

# Marker

> `.autoresearch.yaml` schema, marker states, and lifecycle.

## Overview

The marker is the central interface between human intent and autonomous execution. A `.autoresearch.yaml` file in any repository declares one or more markers, each defining what to improve, how to measure it, and what constraints apply.

## Schema

Each marker contains these sections:

| Section | Purpose |
|---------|---------|
| `name` | Unique identifier within the repo |
| `status` | `active`, `skip`, `paused`, `completed`, `needs_human` |
| `target.mutable` | Glob patterns for files the engine CAN edit |
| `target.immutable` | Harness files — NEVER touched by the engine |
| `metric` | Command to run, extraction pattern, direction, baseline |
| `guard` | Optional regression gate (dual-gate verification) |
| `loop` | Model, budget, max experiments, cost limit |
| `escalation` | Failure thresholds for refine/pivot/search/halt |
| `schedule` | overnight, weekend, on-demand, or cron |
| `auto_merge` | Gate chain, merge target, push/PR flags, lifecycle hooks |
| `agent` | Model, effort, permission mode, allowed/disallowed tools |
| `results` | Branch prefix, notifications, auto-merge |

## Marker States

| State | Meaning |
|-------|---------|
| `active` | Ready to run on next cycle |
| `skip` | Ignored completely |
| `paused` | Preserves branch + results, no new experiments |
| `completed` | Hit target or max experiments |
| `needs_human` | Escalation halted, human intervention required |

## State Override

Status can be overridden locally via `~/.autoresearch/state.json` (not committed). Local override takes precedence over YAML.

## Auto-Merge Section

The `auto_merge` section controls what happens after all experiments complete:

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `enabled` | bool | `false` | Enable post-experiment gate chain + merge |
| `target_branch` | str | `"dev"` | Branch to merge kept changes into |
| `gates` | list[str] | `["security", "tests", "confidence"]` | Gate chain to run before merge |
| `security_command` | str? | `null` | Shell command for security gate |
| `test_command` | str? | `null` | Shell command for test gate |
| `min_confidence` | float | `1.0` | Minimum confidence score to pass |
| `push_to_remote` | bool | `false` | `git push origin <target_branch>` after merge |
| `create_pr` | bool | `false` | `gh pr create` after push (independent of push_to_remote) |
| `snapshot_command` | str? | `null` | Shell command to run before each experiment (see [Engine Hooks](1B-ENGINE.md#lifecycle-hooks)) |
| `restore_command` | str? | `null` | Shell command to run on experiment failure (see [Engine Hooks](1B-ENGINE.md#lifecycle-hooks)) |
| `notify` | list[str] | `[]` | Notification targets |

## File Resolution

The CLI checks for `.autoresearch/config.yaml` first (canonical path), then falls back to `.autoresearch.yaml` at the repo root (legacy). There is no upward directory traversal — the marker file must be in the specified repo path.
