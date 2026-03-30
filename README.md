# tccw-autoresearch

**Agnostic autonomous improvement engine.** Point it at any codebase — it makes it measurably better overnight while you sleep.

Inspired by [karpathy/autoresearch](https://github.com/karpathy/autoresearch) — methodology only, zero code dependency. Clean-room implementation of the loop pattern, stripped of all ML assumptions.

---

## What It Does

```
LOOP:
  1. Edit target files
  2. Run immutable harness
  3. Measure single metric
  4. If improved → keep (git commit)
  5. If worse  → discard (git reset)
  6. REPEAT until budget exhausted
```

Works on anything with a measurable outcome: test pass rates, build times, response latency, error counts, coverage percentages. No GPU. No ML. Tests replace training runs.

---

## The Marker

A `.autoresearch.yaml` in any repository declares what to improve:

```yaml
markers:
  - name: auth-flow-reliability
    description: Improve auth smoke test pass rate
    status: active

    target:
      mutable:
        - src/auth/*.py
      immutable:
        - tests/test_auth.py

    metric:
      command: pytest tests/test_auth.py -q
      extract: "(\d+) passed"
      goal: maximize
      baseline: 28

    loop:
      max_experiments: 50
      budget_hours: 8
```

Add the file, run `autoresearch` — the engine handles the rest.

---

## Usage

```bash
# Interactive TUI (select marker, press 'r' to run)
autoresearch

# Headless — for AI agents, CI/CD, cron
autoresearch run -m auth-flow-reliability --headless

# Remote dispatch via agenticore, GitHub Actions, SSH — same command
autoresearch run -m auth-flow-reliability --headless
```

---

## Intelligence Features

| Feature | Description |
|---------|-------------|
| **Ideas backlog** | Failed experiments log *why* they were interesting — future sessions don't repeat mistakes |
| **Graduated escalation** | 3 failures → REFINE → 5 → PIVOT → 2 PIVOTs → SEARCH → 3 PIVOTs → HALT |
| **Statistical confidence** | MAD-based scoring after 3+ experiments — ignores benchmark noise |
| **Dual-gate guard** | Metric gate + regression guard — prevents gaming the metric by breaking something else |
| **Finalization** | Clean, reviewable branch from messy experimental history |

---

## Installation

```bash
pip install tccw-autoresearch
```

Or from source:

```bash
git clone https://github.com/nestorcolt/tccw-autoresearch
cd tccw-autoresearch
pip install -e .
```

---

## Architecture

```
src/autoresearch/
├── marker.py      # .autoresearch.yaml schema + parser (Pydantic)
├── engine.py      # Core experiment loop
├── worktree.py    # Git worktree isolation per marker
├── metrics.py     # Metric extraction + confidence scoring
├── program.py     # Runtime instruction generation for agent
├── state.py       # Global state (~/.autoresearch/state.json)
├── config.py      # Config defaults (~/.autoresearch/)
├── results.py     # results.tsv read/write
├── ideas.py       # ideas.md backlog
├── cli.py         # CLI entry point (Block 3 — in progress)
└── daemon.py      # Daemon service (Block 4 — planned)
```

**Design principles:**
- **Agnostic** — no assumptions about what it improves
- **Self-contained** — repo + marker file = everything needed to run
- **Dual-mode** — every command works interactively AND headlessly
- **No ML dependencies** — no torch, no CUDA, no GPU

---

## Status

| Block | Description | Status |
|-------|-------------|--------|
| Block 1 | Marker schema, state, results | ✅ Done (143 tests) |
| Block 2 | Engine loop, git isolation | ✅ Done |
| Block 3 | CLI — interactive + headless | 🔲 Ready |
| Block 4 | Daemon + packaging | 🔲 Ready |

---

## License

MIT
