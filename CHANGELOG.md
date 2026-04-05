# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.1.0] - 2026-04-05

### Added
- Core engine: edit → measure → keep/discard experiment loop
- CLI with 13 commands (interactive TUI + headless JSON mode)
- Daemon service with cron scheduling and concurrent runs
- Agent profiles: settings.json + CLAUDE.md generation at runtime
- Permission enforcement: mutable/immutable translated to CLI flags
- Budget countdown hook (PostToolUse additionalContext injection)
- Auto-publish PRs for kept experiments (branch → PR → auto-merge)
- Statistical confidence scoring (MAD-based, after 3+ experiments)
- Graduated escalation: refine → pivot → search → halt
- Ideas backlog: failed experiments log why they were interesting
- `autoresearch init` scaffolding with default agent profile
- Finalization: cherry-pick + squash winning commits
- Telemetry: stream-json parsing into TelemetryReport
- CI workflow (pytest + ruff)
- `/autoresearch` skill (run, status, logs)
- `/onboard` skill (interactive Q&A to configure any repo)
