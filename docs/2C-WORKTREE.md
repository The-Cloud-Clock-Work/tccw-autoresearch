---
layout: default
title: Worktree
parent: Documentation Index
nav_order: 22
---

# Worktree

> Git worktree management, branch naming, parallel runs.

## Overview

The worktree module (`worktree.py`) isolates each marker's experiments in a separate git worktree, preventing interference between parallel runs.

## Lifecycle

1. **Create** — `create_worktree()` sets up a new worktree with a dedicated branch
2. **Execute** — Engine runs experiments within the worktree directory
3. **Commit/Reset** — Changes are committed or discarded in the worktree
4. **Remove** — `remove_worktree()` cleans up after completion

## Branch Naming

Branches follow the `results.branch_prefix` from the marker config (e.g., `autoresearch/auth-flow`).

## Parallel Execution

Each marker gets its own worktree and branch. Multiple markers can run concurrently without git conflicts since worktrees provide filesystem-level isolation.

## Error Handling

`GitError` exceptions are raised for worktree operations that fail (e.g., branch already exists, dirty working directory).
