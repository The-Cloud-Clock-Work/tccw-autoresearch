---
layout: default
title: Documentation Index
has_children: true
permalink: /docs/
nav_order: 1
---

# Documentation Index

## Architecture & Foundation
| File | Topic |
|------|-------|
| [0A-ARCHITECTURE.md](0A-ARCHITECTURE.md) | System architecture, core loop, design principles |
| [0B-QUICKSTART.md](0B-QUICKSTART.md) | Installation, first marker, first run |

## Core Domain
| File | Topic |
|------|-------|
| [1A-MARKER.md](1A-MARKER.md) | .autoresearch.yaml schema, marker states, lifecycle |
| [1B-ENGINE.md](1B-ENGINE.md) | Experiment loop, escalation, commit/discard logic |
| [1C-METRICS.md](1C-METRICS.md) | Metric extraction, guard gates, dual-gate verification |
| [1D-STATE.md](1D-STATE.md) | state.json, local overrides, atomic read-modify-write |

## CLI & Operations
| File | Topic |
|------|-------|
| [2A-CLI.md](2A-CLI.md) | CLI commands, interactive + headless modes |
| [2B-DAEMON.md](2B-DAEMON.md) | Daemon service, scheduling, cron integration |
| [2C-WORKTREE.md](2C-WORKTREE.md) | Git worktree management, branch naming, parallel runs |

## Agent Profiles
| File | Topic |
|------|-------|
| [3A-AGENTS.md](3A-AGENTS.md) | Default agent, copilot agent, profile scaffolding |
| [3B-IDEAS-PROGRAM.md](3B-IDEAS-PROGRAM.md) | Idea generation, program synthesis, finalize flow |
| [3C-BUDGET-COUNTDOWN.md](3C-BUDGET-COUNTDOWN.md) | PostToolUse hook for time awareness, urgency tiers |

## Gates & Auto-Merge
| File | Topic |
|------|-------|
| [1E-GATES.md](1E-GATES.md) | Gate chain, auto-publish PRs, GitHub audit trail |

## Configuration & Telemetry
| File | Topic |
|------|-------|
| [4A-CONFIGURATION.md](4A-CONFIGURATION.md) | Global config, ~/.autoresearch/, env vars |
| [4B-TELEMETRY.md](4B-TELEMETRY.md) | Telemetry, results tracking, results.tsv |

## Harnesses (Production-Validated)
| File | Topic |
|------|-------|
| [6A-HARNESS-RUFF.md](6A-HARNESS-RUFF.md) | Ruff harness — zero infra, 2s execution, production results |
| [6B-PRODUCTION-DEPLOYMENT.md](6B-PRODUCTION-DEPLOYMENT.md) | Step-by-step deployment guide, common issues, scaling |

## Development
| File | Topic |
|------|-------|
| [5A-TESTING.md](5A-TESTING.md) | Test suite, fixtures, running tests |
| [5Z-KNOWN-ISSUES.md](5Z-KNOWN-ISSUES.md) | Known issues & workarounds |

