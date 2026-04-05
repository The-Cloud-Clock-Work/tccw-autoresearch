# 3C — Budget Countdown Hook

## Problem

Agents run on a time budget (e.g., 20 minutes). Without awareness of remaining time, agents spend the entire budget analyzing code and run out before committing. The engine's always-commit catches this, but the agent should know to wrap up.

## Solution

A `PostToolUse` hook injects remaining time as `additionalContext` after every tool call. The agent sees it as a `<system-reminder>` in its context.

### Three Urgency Tiers

| Remaining | Message | Agent behavior |
|-----------|---------|----------------|
| > 5 min | `BUDGET: Xm remaining` | Continue working |
| 2–5 min | `▲ BUDGET: Xm — wrap up and commit soon` | Start finishing |
| < 2 min | `▲▲▲ BUDGET: Xm — STOP EDITING, COMMIT NOW, EXIT ▲▲▲` | Commit immediately |
| Expired | `▲▲▲ BUDGET EXPIRED — COMMIT NOW AND EXIT ▲▲▲` | Emergency commit |

### How It Works

1. Engine sets `AUTORESEARCH_BUDGET_END` env var (Unix timestamp) before spawning agent
2. `hooks/budget-countdown.sh` reads the timestamp, computes remaining seconds
3. Outputs JSON with `hookSpecificOutput.additionalContext` — Claude Code injects this as a system-reminder
4. Agent sees the countdown after EVERY tool call

### Hook Output Format

Claude Code requires this exact JSON structure for `PostToolUse` context injection:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PostToolUse",
    "additionalContext": "▲ BUDGET: 3m12s remaining — wrap up and commit soon"
  }
}
```

Plain stdout from hooks is NOT visible to the agent. Only JSON with `additionalContext` gets injected.

### Wiring

The engine's `agent_profile.py` automatically:
1. Resolves `hooks/budget-countdown.sh` through symlinks
2. Writes a `PostToolUse` hook entry into `settings.local.json` at the agent's CWD
3. Sets `AUTORESEARCH_BUDGET_END` in the subprocess environment

No per-project configuration needed. Every agent inherits this from the default profile.

## Files

| File | Purpose |
|------|---------|
| `src/autoresearch/agents/default/hooks/budget-countdown.sh` | The countdown script |
| `src/autoresearch/agent_profile.py` | Wires hook into settings.local.json |
| `src/autoresearch/engine.py` | Sets `AUTORESEARCH_BUDGET_END` env var |

## Key Discovery

Claude Code hook events and what their stdout does:

| Event | stdout visible to agent? | How? |
|-------|-------------------------|------|
| `SessionStart` | Yes | As system-reminder |
| `UserPromptSubmit` | Yes | As system-reminder |
| `PostToolUse` | **Only via JSON** | `hookSpecificOutput.additionalContext` |
| `Stop` | No | Side-effect only |

Source: `/home/iamroot/dev/claude-code/src/schemas/hooks.ts` — 27 hook events total. The `additionalContext` field is available on `PostToolUse`, `UserPromptSubmit`, and others.
