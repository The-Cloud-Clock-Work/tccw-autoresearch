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

## File Resolution

The CLI checks for `.autoresearch/config.yaml` first (canonical path), then falls back to `.autoresearch.yaml` at the repo root (legacy). There is no upward directory traversal — the marker file must be in the specified repo path.
