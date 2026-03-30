# CLAUDE.md

## Identity

**Project:** tccw-autoresearch -- Agnostic autonomous improvement engine
**Operator:** Nestor Colt
**Protocol:** Concise, precise, structured output. No filler.
**Voice-to-Text:** Operator uses voice-to-text ~90%. English is not native. Resolve mispronunciations silently.

---

## Mission

Build a standalone CLI + daemon that implements the Karpathy autoresearch loop pattern for any codebase. The engine is agnostic -- it knows files, metrics, git, and loops. Nothing else.

**Core architectural principle:** The repo is self-contained. The `.autoresearch.yaml` marker file carries everything. The CLI reads it from the repo, generates agent instructions at runtime, executes in the repo's worktree. No external payloads. No special integrations. Any system that can run `autoresearch run -m <marker> --headless` in a cloned repo is an execution environment -- local terminal, agenticore, GitHub Actions, SSH, cron.

---

## Operator Documents

The `operator/` directory contains the documents that drive all development:

| Document | Purpose | Who Edits |
|----------|---------|-----------|
| `operator/VISION.md` | Design philosophy, intent, principles | **Operator only** -- AI reads, never modifies without explicit instruction |
| `operator/SPECS.md` | Technical specifications, schemas, behavior | Operator + AI (with approval) |
| `operator/BLOCKS.md` | Major work blocks, current status | Operator + AI (update every session) |
| `operator/TODO.md` | Minor items, pending decisions, scratchpad | Operator + AI |

---

## Boot Sequence

Every conversation — no exceptions:
1. Read `operator/VISION.md` — understand the operator's intent and philosophy
2. Read `operator/SPECS.md` — understand the technical contract
3. Read `operator/BLOCKS.md` — understand current state, find the assigned block
4. Read `operator/TODO.md` — check for pending decisions and don't-forget items
5. Identify the active block and start work on it

---

## Workflow Methodology

The operator works in blocks. Each block is an independent plan:

1. **Operator assigns a block** — "work on Block 1" or "plan Block 2"
2. **Agent reads boot sequence** — VISION → SPECS → BLOCKS → TODO
3. **Agent plans the block** — enters plan mode, designs the implementation
4. **Operator approves** — reviews plan, adjusts, confirms
5. **Agent executes** — implements the block, potentially in a worktree
6. **Agent updates state** — marks progress in BLOCKS.md, adds notes to TODO.md
7. **Repeat** — next block or continue current one

Blocks may run in parallel (different worktrees, different agents). Block dependencies are documented — don't start a block if its dependency isn't done.

**Key rule:** Every session ends with updated BLOCKS.md and TODO.md. Progress is never lost between sessions.

---

## Rules

1. **VISION.md is sacrosanct** -- read every session, never modify without explicit operator instruction
2. **SPECS.md is the contract** -- if a detail is in specs, follow it. If not, ask before inventing
3. **BLOCKS.md stays current** -- update block statuses every session to reflect actual progress
4. **Operator drives design** -- no implementation without design approval. Investigate > design > spec > build > verify
5. **No code without design approval** -- operator confirms before implementation begins
6. **Agnostic always** -- no Anton-specific, no K8s-specific, no provider-specific code. If it assumes infrastructure, it's wrong
7. **Dual-mode CLI** -- every command works interactively AND with `--headless`. Use `/enhance-cli` skill to enforce
8. **Git discipline** -- work on `dev` branch, never push to `main`
9. **No secrets in code** -- credentials via env vars only
10. **Test both modes** -- interactive behavior unchanged, headless outputs valid JSON

---

## Project Structure (planned)

```
tccw-autoresearch/
+-- CLAUDE.md                # This file
+-- operator/                # Operator-owned documents
|   +-- VISION.md            # Read every conversation
|   +-- SPECS.md             # Technical contract
|   +-- BLOCKS.md            # Work block tracking
|   +-- TODO.md              # Scratchpad
|   +-- images/              # Screenshots, diagrams
+-- pyproject.toml           # Package definition
+-- src/
|   +-- autoresearch/
|       +-- __init__.py
|       +-- cli.py           # CLI entry point (interactive + headless)
|       +-- daemon.py        # Daemon service
|       +-- engine.py        # Core experiment loop
|       +-- marker.py        # .autoresearch.yaml parser + schema
|       +-- worktree.py      # Git worktree management
|       +-- metrics.py       # Metric extraction + comparison
|       +-- results.py       # Results tracking (results.tsv)
|       +-- config.py        # Global config (~/.autoresearch/)
|       +-- state.py         # State management (state.json)
+-- tests/
+-- .autoresearch.yaml       # Dogfood -- markers for self-improvement
```

---

## Skills (from cc-colt-tools — installed via symlinks at ~/.claude/skills/)

| Skill | Purpose | Use When |
|-------|---------|----------|
| `/operator-init` | Bootstrap operator-driven development — creates `operator/` with VISION, SPECS, BLOCKS, TODO | Setting up a new project or migrating existing docs |
| `/enhance-cli` | Enforce dual-mode CLI: interactive TUI (menus, action keys) + headless (`--headless`, JSON, flags) | Building or refactoring any CLI command |
| `/enforce-deter` | Extract deterministic steps from AI workflows into standalone scripts | Making processes more reliable, reducing token waste |

---

## Dependencies (planned)

- Python 3.10+
- `typer` or `click` -- CLI framework
- `pydantic` -- schema validation for `.autoresearch.yaml`
- `rich` -- TUI rendering (tables, status indicators, menus)
- `gitpython` or subprocess git -- worktree management
- No ML dependencies. No torch. No CUDA. No GPU.
