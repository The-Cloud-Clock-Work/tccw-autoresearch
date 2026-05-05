# From Karpathy's Overnight Loop to a Production Agentic CLI: How tcc-autoresearch Makes Any Codebase Measurably Better While You Sleep

> *"Give an AI agent a small but real LLM training setup and let it experiment autonomously overnight."*
> — Andrej Karpathy, March 7, 2026

---

## Abstract

In March 2026, Andrej Karpathy released [autoresearch](https://github.com/karpathy/autoresearch) — a minimal framework demonstrating that an AI agent, given a metric and permission to edit code, can autonomously discover genuine improvements through an edit-measure-keep/discard loop. Within 48 hours, the repo had 21,000+ GitHub stars. Shopify CEO Tobi Lutke ran it overnight on the Liquid template engine and achieved 53% faster parse+render time.

Karpathy called it *"just a recipe/idea"* — deliberately minimal, single-metric, single-file, tied to ML training. He issued a clear challenge: *"Any metric you care about that is reasonably efficient to evaluate... can be autoresearched by an agent swarm."*

This paper describes **tcc-autoresearch** — a production CLI tool (`pip install tcc-autoresearch`) that answers that challenge. It takes Karpathy's core algorithm and makes it work on **any codebase, any metric, any agent**, with statistical rigor, graduated intelligence, and a full publish pipeline. It ships as a PyPI package with interactive onboarding, a live TUI, a scheduling daemon, and 2,554 tests at 92.4% coverage.

The paradigm didn't change. The execution did.

---

## Part I: The Karpathy Paradigm

### The Three-File Architecture

Karpathy's original autoresearch is three files. This is not accidental minimalism — it is the design:

| File | Role | Who Modifies |
|------|------|-------------|
| `prepare.py` | Fixed constants, data prep, tokenizer, `evaluate_bpb()` | Nobody (locked evaluator) |
| `train.py` | GPT model, optimizer, training loop | The AI agent |
| `program.md` | Human-written agent instructions | The human |

The human programs `program.md`. The agent programs `train.py`. The evaluator in `prepare.py` is the incorruptible referee.

### The Loop

From Karpathy's `program.md`, verbatim:

```
LOOP FOREVER:
1. Look at the git state: the current branch/commit we're on
2. Tune train.py with an experimental idea by directly hacking the code
3. git commit
4. Run the experiment: uv run train.py > run.log 2>&1
5. Read out the results
6. If the run crashed, read the stack trace and attempt a fix
7. Record results in the tsv
8. If val_bpb improved (lower), "advance" the branch, keeping the commit
9. If val_bpb is equal or worse, git reset back to where you started
```

And the directive that makes it autonomous:

> **NEVER STOP**: Once the experiment loop has begun, do NOT pause to ask the human if you should continue... The human might be asleep... You are autonomous. If you run out of ideas, think harder.

### The Metric: A Locked Evaluator

The fitness signal is `val_bpb` (validation bits per byte) — lower is better, vocab-size-independent, computed inside `prepare.py` which the agent cannot modify. This is the critical design decision: **the agent cannot hack the reward function**. The evaluator is immutable.

Each experiment runs for exactly 5 minutes wall-clock time, yielding ~12 experiments per hour, ~100 experiments per sleep cycle.

### The Git Ratchet

If the metric improves: the commit stays, becoming the new baseline. If equal or worse: `git reset HEAD~1` wipes it. The branch only advances on genuine improvements — a strict monotonic ratchet. Results are logged to `results.tsv` (untracked by git, so the full experimental history survives branch resets).

### The Simplicity Criterion

A non-obvious constraint from the original program.md:

> *"Simplicity criterion: All else being equal, simpler is better. A small improvement that adds ugly complexity is not worth it. Conversely, removing something and getting equal or better results is a great outcome — that's a simplification win."*

This prevents codebase bloat and maintains the agent's ability to reason about the code across sessions.

### Results That Turned Heads

Karpathy left autoresearch running for ~2 days on a depth-12 GPT model:

- **~700 experiments** executed
- **~20 genuine additive improvements** found
- GPT-2 training time: **2.02 hours -> 1.80 hours (11% speedup)**
- Found a **missing scalar multiplier in QK-Norm attention** that Karpathy himself had missed
- Discovered misconfigured AdamW parameters and untuned weight decay schedules

Then Shopify CEO Tobi Lutke ran it on **Liquid** — the Ruby template engine powering every Shopify storefront, a codebase he originally wrote 20+ years ago:

- 120 experiments, 93 commits, all 974 unit tests passing
- **53% faster combined parse+render time**
- **61% fewer memory allocations**
- Key discovery: replacing `StringScanner` with `String#byteindex` was ~40% faster alone

Karpathy's reaction: *"Who knew early singularity could be this fun?"*

Simon Willison's insight from analyzing the Liquid PR: robust test coverage is what makes "make it faster" a computationally actionable goal — the test suite acts as a correctness harness, not just a check.

### The Vision Beyond

The day after release, Karpathy posted a follow-up vision:

> *"The next step for autoresearch is that it has to be asynchronously massively collaborative for agents (think: SETI@home style). The goal is not to emulate a single PhD student, it's to emulate a research community of them."*

> *"Any metric you care about that is reasonably efficient to evaluate... can be autoresearched by an agent swarm."*

And on the strategic implication for frontier labs:

> *"All LLM frontier labs will do this. It's the final boss battle."*

### What He Didn't Build

Karpathy was explicit about scope. His autoresearch is:

- A recipe, not a tool — *"you don't 'use it' directly, it's just a recipe/idea"*
- Single-file modifiable (`train.py` only)
- Single metric (`val_bpb` hardcoded)
- No CLI, no configuration, no packaging
- No statistical validation of improvements
- No publish/merge pipeline
- No scheduling or daemon
- No support commitment — *"just a demonstration and I don't know how much I'll support it going forward"*
- Agent-agnostic but practically Claude-only (OpenAI Codex *"ignores the instruction to never stop"*)

The community forked it for platform coverage (`autoresearch-macos`, `autoresearch-mlx`, `autoresearch-win-rtx`), but nobody generalized the algorithm itself.

---

## Part II: The Generalization Problem

Karpathy's loop works because he made three things fixed: the metric, the mutable scope, and the git mechanism. But generalizing this to "any codebase, any metric" exposes problems the original doesn't face:

**1. What if the agent gets stuck?** The original says "think harder." A production system needs graduated intervention: nudge, then redirect, then research, then halt.

**2. What if the improvement regresses something else?** Fixing lint errors could break tests. The original has one metric. Production needs a dual-gate: improve X without regressing Y.

**3. What if improvement is noise?** The original keeps anything strictly better. But metrics are noisy — 0.001 improvement might be measurement variance. Production needs statistical confidence.

**4. What if the agent tries the same failed approach repeatedly?** The original has no memory between experiments within a session beyond the git state. Production needs an ideas backlog.

**5. What if you want this on your project?** The original requires understanding Karpathy's code, adapting `program.md`, setting up the evaluator manually. Production needs `pip install` and three commands.

**6. What if you want it to run every night?** The original is a one-shot manual handoff. Production needs a daemon with cron scheduling.

**7. What if the improvements should actually ship?** The original produces a git branch. Production needs PR creation, gate validation, and auto-merge.

---

## Part III: tcc-autoresearch — The Production Answer

### Three Commands

```bash
pip install tcc-autoresearch
cd /path/to/your-project
autoresearch init    # Claude scans your project, asks questions, writes config
autoresearch run     # experiments begin
```

That's it. No Docker, no GPU, no ML framework. Python 3.10+ and Claude Code on PATH.

`autoresearch init` spawns an interactive Claude session that scans your tech stack, suggests metrics, asks about file boundaries, measures a baseline, and writes `.autoresearch/config.yaml`. Everything is configurable. Nothing requires manual YAML editing.

### The Marker: One YAML Block Per Improvement Objective

```yaml
markers:
  - name: lint-quality
    description: "Reduce ruff lint errors to zero"
    target:
      mutable: ["src/**/*.py"]
      immutable: ["tests/**/*.py"]
    metric:
      command: "ruff check src/ 2>&1"
      extract: "grep -oP 'Found \\K\\d+'"
      direction: lower
      baseline: 42
      issues_command: "ruff check src/ --output-format concise | head -30"
    guard:
      command: "pytest tests/ -q --tb=no 2>&1 | tail -1"
      extract: "grep -oP '\\d+(?= passed)'"
      threshold: 100
    agent:
      model: sonnet
      budget_per_experiment: 10m
      max_experiments: 50
      env_file: .env
    auto_merge:
      enabled: true
      target_branch: main
    schedule:
      type: overnight
```

The metric is any shell command that produces a number. `ruff check`, `pytest`, `eslint`, `cargo test`, `time make build`, a custom script — if it outputs a number, it can be autoresearched.

The guard is a second, independent metric that must not regress. Improve lint without breaking tests. Improve speed without dropping coverage. The dual-gate pattern.

`target.mutable` and `target.immutable` are Karpathy's locked evaluator, generalized. The agent can edit `src/**/*.py` but not `tests/**/*.py`. This is enforced at two levels: Claude Code's permission system (`settings.json` with `dontAsk` mode) AND CLI flags (`--disallowedTools`). Dual enforcement — even if one mechanism has a bug, the other catches it.

### The Seven Innovations Over Karpathy

#### 1. Graduated Escalation (The EscalationState Machine)

Karpathy's loop says "think harder" when stuck. tcc-autoresearch implements a 4-tier state machine that tracks failure patterns and adapts the agent's instructions:

| Consecutive Failures | Level | Agent Directive |
|---------------------|-------|----------------|
| 3 (default) | **refine** | Adjust strategy within current approach, consult ideas backlog |
| 5 | **pivot** | Abandon current approach, try a fundamentally different direction |
| 2 pivots without progress | **search** | Research external solutions before coding |
| 3 total pivots | **halt** | Stop the loop, flag marker as NEEDS_HUMAN |

A single successful keep resets the entire failure chain. This asymmetry is intentional: failure escalates incrementally, but success resets completely. The escalation level is injected into the agent's prompt as a human-readable directive — the agent never sees raw counters.

#### 2. Dual-Gate Guard (Improve X, Don't Break Y)

Every kept experiment passes two sequential gates:

- **Metric Gate:** Is the metric strictly better than the current best (not just baseline)?
- **Guard Gate:** Does an independent command (tests, coverage, security scan) still pass its threshold?

If the guard fails, the engine doesn't immediately discard. It re-invokes the agent with the guard failure output, giving it a chance to fix the regression (up to `rework_attempts` times). Only after exhausting rework does it discard.

Near-misses — experiments that improved the metric but failed the guard — are recorded in the ideas backlog with the guard failure details, informing future experiments.

#### 3. Statistical Confidence via MAD

After 3+ kept experiments, the engine computes a confidence score using Median Absolute Deviation:

```
confidence = |current - baseline| / (MAD * 1.4826)
```

The 1.4826 factor is the standard consistency constant that makes MAD equivalent to standard deviation for normal distributions. MAD is robust to outliers — a single anomalous improvement doesn't inflate the spread estimate and suppress the score.

Confidence feeds the auto-merge gate chain: `min_confidence: 1.0` means "the improvement signal is above the noise floor." Labels: >= 2.0 HIGH, >= 1.0 MEDIUM, < 1.0 LOW.

#### 4. Ideas Backlog (Institutional Memory)

Every discarded experiment writes to `.autoresearch/<marker>/ideas.md`:

- What was tried and why it was discarded (metric value, guard failure)
- Agent permission denials (tried to edit an immutable file)
- Telemetry-extracted errors

At the start of each experiment, the full ideas backlog is appended to the agent's prompt. The agent sees what has already failed and why — preventing repeated attempts at the same dead approach.

The ideas backlog is committed to git. It persists across sessions, machines, and team members. It shows up in the PR diff.

#### 5. Agent Commit Detection (HEAD Before/After)

Claude Code, when given `bypassPermissions`, may commit on its own. The engine captures `HEAD` before invoking the agent and compares after. Three cases:

1. Agent changed files but didn't commit -> engine commits
2. Agent committed itself -> engine detects HEAD moved
3. Neither -> experiment discarded as "no changes"

No work is silently lost, even on timeout.

#### 6. Budget Countdown Hook

A PostToolUse hook reads `AUTORESEARCH_BUDGET_END` (a Unix timestamp injected by the engine) and injects time-remaining context into Claude's conversation after every tool call:

- Normal: no injection
- Wrap-up phase: "Budget warning: N minutes remaining. Start wrapping up."
- Final minutes: "COMMIT NOW."

This prevents the common failure mode where the agent is mid-edit when time expires.

#### 7. Full Publish Pipeline

The original autoresearch produces a git branch. tcc-autoresearch ships a complete publish pipeline:

1. Push experiment branch to remote
2. Create PR via `gh pr create` with metric delta in the body
3. Run 5-gate chain: metric, quality gate, security, tests, confidence
4. If all gates pass and `auto_merge.enabled`: squash-merge via GitHub API
5. One branch, one PR per run — no intermediate branches

The gate chain is independently configurable. Gates 2-5 are skipped when not configured, enabling gradual adoption.

### The Onboarding Experience

`autoresearch init` spawns Claude with a 14-step onboarding skill that mixes deterministic shell scripts (repo validation, baseline measurement, git setup) with AI-judgment steps (stack detection, metric suggestion, file boundary recommendations).

The skill runs on the most capable model available. It scans your project, asks what you want to improve, suggests proven metric commands for your stack, picks mutable/immutable boundaries, measures a baseline, writes config, and registers the marker. The human answers questions. The AI does the rest.

### The Daemon

```bash
autoresearch daemon start
```

Double-fork Unix daemon. PID file. Cron evaluation via `croniter`. Threading with concurrency semaphore. Four schedule types: `on-demand`, `overnight` (1am daily), `weekend` (Saturday 1am), `cron` (custom expression). The daemon calls the same `run_marker()` function as the interactive CLI — no separate code path.

### The Live TUI

During runs, a Rich Live panel shows real-time experiment progress:

```
 +-autoresearch * my-repo:lint-quality -----------------+
 | Baseline: 42 -> Current: 12 (lower)  *  Budget: 10m |
 |                                                      |
 | ######### 5/50  Kept: 3  Disc: 2  Crash: 0          |
 |                                                      |
 |  #  Status   Metric  Delta  Description              |
 |  1  KEEP        38     -4   Fixed import ordering    |
 |  2  DISCARD     38      0   No unused imports found  |
 |  3  KEEP        29     -9   Removed dead code paths  |
 |  4  KEEP        12    -17   Applied autofix rules    |
 |  5  * running...                                     |
 +------------------------------------------------------+
```

Every command supports `--headless` for JSON output. The TUI and headless modes are not separate codepaths — they share the same engine, same callbacks, different renderers.

---

## Part IV: Production Validation

### E2E on agentihooks-bundle

The system was validated end-to-end on a real project (not itself):

1. `pip install tcc-autoresearch` in a fresh venv
2. `autoresearch init` -> Claude scanned the project, asked questions, wrote config
3. `autoresearch run` -> 10 experiments with Rich Live progress panel
4. Baseline 1 -> 16 skill documentation files created
5. PR created -> reviewed -> merged to main
6. No log artifacts in PR (`.gitignore` working)
7. `autoresearch clean` removed stale experiment branches

### Quality Metrics

| Metric | Value |
|--------|-------|
| Unit tests | 2,554 |
| Integration tests | 25 |
| SonarQube coverage | 92.4% |
| Bugs | 0 |
| Vulnerabilities | 0 |
| Code smells | 12 |
| Ruff errors | 0 |

### Self-Improvement Loop

tcc-autoresearch was used to improve `antoncore` (the infrastructure monorepo it was built for):

| Run | Before | After | Delta | PR |
|-----|--------|-------|-------|----|
| 1 | 186 ruff errors | 163 | -23 | manual |
| 2 | 163 | 133 | -30 | #218 |
| 3 | 133 | 0 | -133 | #219 |

Three overnight runs. 186 lint errors to zero. Each run produced a PR with full audit trail.

---

## Part V: The Paradigm Comparison

| Dimension | Karpathy's autoresearch | tcc-autoresearch |
|-----------|----------------------|------------------|
| **Nature** | Recipe/idea/demonstration | Production CLI tool |
| **Installation** | Clone repo, read program.md, adapt manually | `pip install tcc-autoresearch` |
| **Onboarding** | Write your own program.md | `autoresearch init` (interactive AI wizard) |
| **Metric** | Hardcoded `val_bpb` in locked Python file | Any shell command that outputs a number |
| **Scope** | Single file (`train.py`) | Any set of globs (`src/**/*.py`) |
| **Guard** | None (single metric) | Independent regression guard with rework |
| **When stuck** | "Think harder" | 4-tier graduated escalation (refine/pivot/search/halt) |
| **Memory** | None between experiments | Ideas backlog committed to git |
| **Statistical rigor** | None (any improvement counts) | MAD-based confidence after 3+ keeps |
| **Time management** | Fixed 5-minute training budget | Budget countdown hook injected into agent context |
| **Commit handling** | Agent must commit manually | Engine detects agent commits OR commits for it |
| **Output** | Git branch with interleaved commits | PR with gate-validated auto-merge |
| **Scheduling** | Manual handoff to agent | Daemon with cron (overnight, weekend, custom) |
| **UX** | Terminal output | Rich Live TUI + headless JSON dual-mode |
| **Configuration** | Edit program.md | YAML config with Pydantic validation |
| **Agent** | Claude (practical requirement) | Configurable (model, effort, budget, tools) |
| **Tests** | None | 2,554 unit + 25 integration |
| **Packaging** | GitHub repo | PyPI package with CI/CD |

The core algorithm is identical: **edit -> measure -> keep/discard -> repeat**. The git ratchet is the same. The locked evaluator principle is the same (enforced via `target.immutable` instead of a Python file the agent can't access). The "NEVER STOP" directive is the same (now enforced via budget countdown hooks).

What changes is everything around the loop: the intelligence when stuck, the safety when regressing, the rigor when keeping, the memory when repeating, the pipeline when shipping, and the experience when running.

---

## Part VI: What This Means

Karpathy framed autoresearch as *"not to emulate a single PhD student, it's to emulate a research community."* His implementation emulates one PhD student running one experiment. tcc-autoresearch emulates one research community member who:

- **Knows what failed before** (ideas backlog)
- **Adapts strategy when stuck** (graduated escalation)
- **Doesn't break what works** (dual-gate guard)
- **Has statistical standards** (MAD confidence)
- **Ships results** (PR + gate chain + auto-merge)
- **Shows up every night** (daemon scheduling)
- **Works on any project** (configurable metrics)

The bet is simple: if you can express "better" as a shell command that outputs a number, and you can point the agent at the right files, the system will find improvements. Not always. Not every night. But measurably, verifiably, with a full audit trail and a clean PR.

Karpathy said: *"It's a lot more complex at scale of course... doing it is 'just engineering' and it's going to work."*

This is the engineering.

---

## Links

- **tcc-autoresearch:** [PyPI](https://pypi.org/project/tcc-autoresearch/) | [GitHub](https://github.com/The-Cloud-Clockwork/tcc-autoresearch) | [Docs](https://the-cloud-clockwork.github.io/tcc-autoresearch/)
- **Karpathy's autoresearch:** [GitHub](https://github.com/karpathy/autoresearch) (53,500+ stars)
- **Karpathy's program.md:** [Direct link](https://github.com/karpathy/autoresearch/blob/master/program.md)
- **Shopify/Liquid results:** [Simon Willison's analysis](https://simonwillison.net/2026/Mar/13/liquid/)

---

*Built by [The Cloud Clockwork](https://github.com/The-Cloud-Clockwork). 100/100 production-validated. Every claim in this document has a corresponding test, PR, or commit.*
