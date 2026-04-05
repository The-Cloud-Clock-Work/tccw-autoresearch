---
layout: default
title: Daemon
parent: Documentation Index
nav_order: 21
---

# Daemon

> Daemon service, scheduling, cron integration.

## Overview

The daemon (`daemon.py`) runs as a background service, monitoring tracked markers and executing improvement loops on schedule.

## Scheduling

Markers declare their schedule in `.autoresearch.yaml`:

| Type | When |
|------|------|
| `overnight` | Runs during off-hours |
| `weekend` | Runs on weekends |
| `on-demand` | Manual trigger only |
| `cron` | Custom cron expression (uses `croniter`) |

## Duration Limits

`schedule.duration_hours` caps total runtime per scheduled execution.

## Operation

The daemon checks tracked markers, evaluates schedules, and spawns experiment loops in isolated worktrees. Multiple markers can run concurrently.
