---
layout: default
title: State
parent: Documentation Index
nav_order: 13
---

# State

> `state.json`, local overrides, atomic read-modify-write.

## Overview

The state module (`state.py`) manages persistent state across runs via `state.json`. It tracks marker progress, experiment counts, and local status overrides.

## State File

Located at `~/.autoresearch/state.json`. Contains:

- Tracked markers and their effective statuses
- Experiment history references
- Local status overrides (take precedence over `.autoresearch/config.yaml`)

## Atomic Operations

State updates use atomic read-modify-write to prevent race conditions when multiple markers or daemon processes access the file concurrently.

## Effective Status Resolution

```
1. Check state.json for local override
2. If found → use override
3. If not → use status from `.autoresearch/config.yaml`
```

## Tracking

Markers must be tracked in state before the engine will process them. The CLI handles this via `autoresearch add` (register) and `autoresearch detach` (unregister).
