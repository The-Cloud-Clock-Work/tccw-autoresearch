---
description: Core rules for autoresearch autonomous agents
globs: "**/*"
alwaysApply: true
---

- You are autonomous. NEVER ask for human input or confirmation.
- NEVER edit files outside your mutable set. The permission system will deny it.
- NEVER run destructive git operations: push, rebase, merge, reset --hard.
- NEVER install new dependencies or modify package configs.
- Commit every meaningful change with a descriptive message.
- Keep changes minimal and focused. One logical change per commit.
- If stuck after 3 attempts, try a fundamentally different approach.
- If a permission is denied, pick a different file or strategy.
