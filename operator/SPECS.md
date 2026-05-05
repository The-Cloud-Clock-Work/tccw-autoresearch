# SPECS.md -- Technical Specifications

> **Last updated:** 2026-03-30
> **Status:** Design phase -- no implementation yet

---

## 1. Marker File

### 1.1 Location
- **Canonical path:** `.autoresearch/config.yaml` (inside the `.autoresearch/` directory)
- **Legacy fallback:** `.autoresearch.yaml` at repo root (still supported, checked second)
- One file per repo
- Multiple marker blocks inside a single file

### 1.2 Schema

```yaml
markers:
  - name: string                    # Unique within this repo (e.g. "auth-flow-reliability")
    description: string             # Human-readable purpose
    status: active | skip | paused | completed

    target:
      mutable:                      # Files the engine CAN edit
        - src/auth/*.py
        - lib/utils.py
      immutable:                    # Harness files -- NEVER touched
        - tests/test_auth.py
        - tests/benchmark_auth.sh

    metric:
      command: string               # Shell command to run harness (e.g. "pytest tests/test_auth.py -q")
      extract: string               # Grep/awk to pull single number (e.g. "grep -oP '\\d+(?= passed)'")
      direction: lower | higher     # Which direction is improvement
      baseline: number              # Starting value (measured before first experiment)
      target: number | null         # Goal value -- marker auto-completes when reached (optional)

    guard:                          # Optional regression gate (dual-gate verification)
      command: string | null        # Shell command for regression check (e.g. "pytest tests/ -q --tb=no")
      extract: string | null        # Grep to pull pass/fail (e.g. "grep -oP '\\d+(?= passed)'")
      threshold: number | null      # Minimum acceptable value (below = guard fails)
      rework_attempts: integer      # Attempts to fix before discarding (default: 2)

    agent:
      model: string                 # LLM model (e.g. "sonnet", "opus", "haiku")
      budget_per_experiment: string  # Time limit per experiment (e.g. "10m", "5m")
      max_experiments: integer      # Hard cap on total experiments
      max_cost: string | null       # Spending limit (e.g. "$10") -- optional

    escalation:                     # Graduated failure escalation thresholds
      refine_after: integer         # Consecutive failures before REFINE (default: 3)
      pivot_after: integer          # Consecutive failures before PIVOT (default: 5)
      search_after_pivots: integer  # PIVOTs without progress before SEARCH (default: 2)
      halt_after_pivots: integer    # Total PIVOTs before HALT with needs_human (default: 3)

    schedule:
      type: overnight | weekend | on-demand | cron
      cron: string | null           # Cron expression (e.g. "0 1 * * 6" for Saturday 01:00)
      duration_hours: integer | null # Max runtime in hours

    results:
      branch_prefix: string         # Git branch naming (e.g. "autoresearch/auth-flow")
      notify: list[string]          # Notification channels (e.g. ["ntfy", "telegram", "email"])
      auto_merge: boolean           # Whether to auto-merge winners (default: false)
```

### 1.3 Marker States

| State | Meaning | Engine Behavior |
|-------|---------|----------------|
| `active` | Ready to run | Executes on next run/daemon cycle |
| `skip` | Excluded from execution | Engine ignores completely |
| `paused` | Was active, operator paused | Preserves branch + results, no new experiments |
| `completed` | Hit target metric or max experiments | Stopped naturally, results preserved |

### 1.4 State Override
- `status` can be set in two places:
  1. In `.autoresearch.yaml` (committed, shared)
  2. In `~/.autoresearch/state.json` (local override, not committed)
- Local override takes precedence over YAML
- Use case: operator wants to skip a marker temporarily for troubleshooting without modifying the repo

### 1.5 Marker ID Format
- `repo_name:marker_name` (e.g. `antoncore:auth-flow-reliability`)
- `repo_name` derived by stripping the directory name from the repo path
- Conflict handling: if two repos have same directory name, CLI warns and uses full path as fallback

---

## 2. CLI Tool (`autoresearch`)

### 2.1 Dual-Mode Requirement
Every command MUST support both:
- **Interactive mode** (default) -- TUI with menus, selections, status indicators
- **Headless mode** (`--headless` flag) -- JSON output, all inputs via flags, no prompts

The `/enhance-cli` skill enforces this pattern during development.

### 2.2 Global Flags

| Flag | Purpose |
|------|---------|
| `--headless` | Non-interactive mode. JSON output, no prompts |
| `--verbose` | Extended output for debugging |
| `--config PATH` | Override global config location (default: `~/.autoresearch/config.yaml`) |

### 2.3 Home Directory Behavior (no `.autoresearch.yaml` in CWD)

Displays all tracked markers across all repos:

```
$ autoresearch

+-- AutoResearch -- 4 markers tracked

  #  Repo                  Marker                   Status     Last Run
  1  antoncore             auth-flow-reliability     * active   2h ago
  2  antoncore             build-speed               o skip     --
  3  tcc-autoresearch     engine-tests              * active   14h ago
  4  agenticore            worktree-perf             # paused   3d ago

  [1-4] Select marker    [a] Add marker    [d] Detach marker
  [p] Add by path        [r] Run selected  [R] Run all active in repo
  [q] Quit
```

### 2.4 Repo Directory Behavior (`.autoresearch.yaml` present in CWD)

Auto-detects marker file, shows this repo's markers, prompts to register untracked ones:

```
$ cd /home/iamroot/dev/antoncore
$ autoresearch

+-- Found .autoresearch.yaml in current directory (antoncore)
  -> 3 markers: auth-flow-reliability, build-speed, deploy-speed
  -> 2 already tracked, 1 new

  Register "deploy-speed"? [Y/n]
```

### 2.5 Action Keys

| Key | Context | Action |
|-----|---------|--------|
| `1-N` | Main list | Select/highlight marker |
| `r` | Marker highlighted | Run THAT single marker |
| `R` | Main list | Run all active markers in the highlighted marker's repo |
| `a` | Main list | Add marker -- auto-detect `.autoresearch.yaml` in CWD |
| `p` | Main list | Add by explicit path to a repo |
| `d` | Main list | Detach marker from tracking (does NOT delete YAML from repo) |
| `q` | Any | Quit |

### 2.6 Marker Submenu (after selecting a marker)

```
+-- antoncore:auth-flow-reliability [active]

  Baseline: 24    Current: 31    Target: 34    Direction: higher
  Branch: autoresearch/auth-flow-reliability-mar30
  Last run: 2h ago (12 experiments, 8 kept, 4 discarded)

  [r] Run now         [s] Status details    [t] Results (TSV)
  [k] Skip/Unskip     [p] Pause/Resume      [e] Edit config
  [b] View branch     [i] Ideas backlog     [c] Confidence
  [f] Finalize        [m] Merge winner      [q] Back
```

### 2.7 Headless Equivalents

| Interactive | Headless |
|------------|----------|
| `autoresearch` (TUI) | `autoresearch --headless list` |
| Select marker + `r` | `autoresearch --headless run --marker antoncore:auth-flow-reliability` |
| `R` (run all in repo) | `autoresearch --headless run --repo antoncore` |
| `a` (add) | `autoresearch --headless add --path /home/iamroot/dev/antoncore` |
| `d` (detach) | `autoresearch --headless detach --marker antoncore:build-speed` |
| Submenu status | `autoresearch --headless status --marker antoncore:auth-flow-reliability` |
| Submenu results | `autoresearch --headless results --marker antoncore:auth-flow-reliability` |
| Skip/unskip | `autoresearch --headless skip --marker antoncore:build-speed` |
| Ideas backlog | `autoresearch --headless ideas --marker antoncore:auth-flow-reliability` |
| Confidence | `autoresearch --headless confidence --marker antoncore:auth-flow-reliability` |
| Finalize | `autoresearch --headless finalize --marker antoncore:auth-flow-reliability` |
| Merge | `autoresearch --headless merge --marker antoncore:auth-flow-reliability` |

All headless commands output JSON to stdout and errors to stderr. Exit codes: 0 success, 1 failure, 2 invalid input.

---

## 3. Daemon (`autoresearch daemon`)

### 3.1 Purpose
Long-running local process that watches tracked repos and executes scheduled markers.

### 3.2 Commands

| Command | Purpose |
|---------|---------|
| `autoresearch daemon start` | Start daemon in background |
| `autoresearch daemon stop` | Stop daemon |
| `autoresearch daemon status` | Show daemon state, next scheduled runs |
| `autoresearch daemon logs` | Tail daemon log output |

### 3.3 Behavior
- Reads `~/.autoresearch/state.json` for tracked markers
- Reads each marker's `schedule` block from `.autoresearch.yaml`
- Executes markers when their schedule fires
- Only runs markers with `status: active`
- Writes state updates back to `state.json` after each run
- Process management: PID file at `~/.autoresearch/daemon.pid`

### 3.4 Not Yet Designed
- Polling interval for schedule evaluation
- Repo watching mechanism (poll vs filesystem events)
- Log rotation
- Crash recovery / auto-restart
- Resource limits (max concurrent markers)

---

## 4. Engine (the loop)

### 4.1 Core Loop

```
FOR each experiment (up to max_experiments):
  1. Read current code state and results history
  2. LLM agent proposes a hypothesis (what to change and why)
  3. Agent edits mutable target files
  4. Git commit with descriptive message
  5. Run metric harness: <command> > run.log 2>&1
  6. Extract result: <extract> from run.log
  7. If empty --> crash --> attempt fix or discard
  8. Log to results.tsv (commit, metric, status, description)
  9. DECISION GATE:
     - Metric improved --> KEEP (branch advances)
     - Metric equal or worse --> DISCARD (git reset --hard to previous commit)
  10. REPEAT -- NEVER STOP until budget exhausted
```

### 4.2 Git Worktree Isolation
- Each marker gets its own `git worktree`
- Branch naming: `autoresearch/<marker-name>-<date>` (e.g. `autoresearch/auth-flow-mar30`)
- Worktree created in a temporary location (configurable)
- Parallel markers NEVER share a worktree -- complete isolation
- Worktree cleaned up after completion (configurable: keep or remove)

### 4.3 Immutable Harness Rule
- Files listed in `target.immutable` are NEVER edited by the engine or the LLM agent
- The agent's instructions explicitly forbid editing these files
- These files ARE the metric -- editing them would be gaming the score

### 4.4 Crash Handling
- If metric extraction returns empty --> run crashed
- Agent reads last 50 lines of `run.log` for error diagnosis
- Typo/syntax error --> fix and retry (counts as same experiment)
- Fundamental failure --> discard, log as `crash`, move on
- Feeds into graduated failure escalation (see 4.8)

### 4.5 Simplicity Criterion
- Marginal improvement + added complexity = probably discard
- Equal result + less code = keep (simplification win)
- Enforced via agent instructions (part of the program.md template)

### 4.6 Self-Contained Execution Model

The repo is the source of truth. The CLI reads `.autoresearch.yaml` from the repo, generates agent instructions at runtime, and executes the loop in a worktree of that same repo. No external payloads, no config serialization, no special dispatch formats.

**Local execution flow:**
```
autoresearch run -m <marker>
    |-- reads .autoresearch.yaml from repo root
    |-- validates marker config
    |-- creates git worktree + branch
    |-- generates program.md (ephemeral, from marker config)
    |-- invokes LLM agent with program.md as instructions
    |-- agent edits files, engine runs harness, measures, keeps/discards
    |-- writes results to .autoresearch/<marker>/results.tsv
    |-- loops until budget exhausted
```

**Remote/deferred execution:**
Any system that can clone the repo and run a shell command can execute markers. No adapters needed.

```bash
# Agenticore dispatch
run_task(repo_url="...", task="autoresearch run -m auth-flow --headless")

# GitHub Actions step
run: autoresearch run -m auth-flow --headless

# Cron on any machine
0 1 * * * cd /path/to/repo && autoresearch run -m auth-flow --headless

# SSH to remote
ssh server "cd repo && autoresearch run -m auth-flow --headless"
```

**Prerequisite for remote execution:**
The `autoresearch` CLI must be installed in the execution environment. Options:
- `pip install tcc-autoresearch` (from PyPI or private index)
- Pre-installed in container image (for agenticore, CI runners)
- Vendored as a script in the target repo (zero-dependency fallback, future consideration)

**No executor abstraction layer.** The CLI is the interface. Any system that runs `autoresearch run -m <marker> --headless` is an executor. No plugins, no adapters, no integration code.

### 4.8 Graduated Failure Escalation

Instead of a flat circuit breaker, the engine escalates through increasingly drastic strategies:

```
CONSECUTIVE FAILURES:
  0-2  --> normal operation (retry with new hypothesis)
  3    --> REFINE: agent adjusts strategy within current approach
           Log: "REFINE triggered at experiment N"
           Agent reads ideas.md for alternative angles on same direction
  5    --> PIVOT: agent abandons current approach entirely
           Log: "PIVOT triggered at experiment N (approach: <name>)"
           Agent picks a fundamentally different direction
           Consecutive failure counter resets
  2 PIVOTs without progress --> SEARCH: external web research
           Agent searches for solutions, papers, patterns
           Results appended to ideas.md
           Consecutive failure counter resets
  3 PIVOTs total --> HALT: marker status set to "needs_human"
           Log: "HALT — 3 PIVOTs exhausted, human intervention required"
           Notification sent via configured channels
           Loop stops. Operator reviews ideas.md + results.tsv
```

Thresholds configurable per marker via `escalation:` block in `.autoresearch.yaml`. Defaults: refine=3, pivot=5, search_after_pivots=2, halt_after_pivots=3.

### 4.9 Guard Command (Dual-Gate Verification)

Two independent gates before keeping an experiment:

```
AFTER metric extraction:
  Gate 1: Did the primary metric improve?
    NO  --> DISCARD (standard behavior)
    YES --> proceed to Gate 2

  Gate 2: Does the guard pass? (optional, if guard.command defined)
    YES --> KEEP
    NO  --> REWORK (up to guard.rework_attempts, default 2)
            Agent reads guard output, attempts to fix regression
            If fixed --> KEEP
            If still failing after N attempts --> DISCARD
```

The guard is a separate command from the metric harness. Typical use: metric = "response time" (specific), guard = "full test suite passes" (broad). Prevents the agent from optimizing the specific metric while breaking everything else.

Guard files are added to `target.immutable` — the agent cannot modify the guard harness.

### 4.10 Statistical Confidence Scoring

After 3+ experiments with `keep` status, the engine computes confidence:

```
METHOD: Median Absolute Deviation (MAD)
  1. Collect all kept metric values
  2. Compute median and MAD of the series
  3. confidence = |current - baseline| / (MAD * 1.4826)
     (1.4826 normalizes MAD to standard deviation equivalent)

INTERPRETATION:
  >= 2.0  --> HIGH confidence (green)  -- improvement is real
  1.0-2.0 --> MEDIUM confidence (yellow) -- possibly noise
  < 1.0   --> LOW confidence (red) -- likely noise

DISPLAY:
  In CLI status: "conf: 2.1x" with color indicator
  In results.tsv: confidence column added after 3+ kept experiments
```

Confidence scoring does NOT affect keep/discard decisions — it's informational. The operator uses it to judge whether to merge the winning branch. Future: configurable minimum confidence threshold for auto-merge.

### 4.11 Ideas Backlog (Failure Memory)

Each marker maintains an ideas backlog at `.autoresearch/<marker>/ideas.md`:

```markdown
# Ideas Backlog — auth-flow-reliability

## Discarded but Promising
- **Connection pooling with async** (exp #12, discarded: guard failed)
  Why interesting: 15% metric improvement before guard caught thread safety issue
  Revisit when: thread-safe pool implementation available

- **Remove retry logic, rely on circuit breaker** (exp #8, discarded: metric regressed)
  Why interesting: simplified code significantly (-40 lines)
  Revisit when: circuit breaker library is more mature

## Near-Misses
- **Batch token refresh** (exp #15, discarded: 0.5% improvement, noise range)
  Could work with: larger batch sizes, worth retrying after confidence improves

## External Research (from SEARCH escalation)
- Found pattern: exponential backoff with jitter (source: AWS architecture blog)
  Not yet tried. Relevant to token refresh reliability.
```

**Lifecycle:**
1. Agent reads `ideas.md` at the START of each experiment session
2. When an experiment is discarded, agent writes an entry explaining why the direction had merit
3. When SEARCH escalation fires, external findings are appended
4. Agent uses ideas.md to avoid re-trying identical approaches and to build on near-misses
5. ideas.md is committed to the autoresearch branch alongside results.tsv

### 4.12 Finalization Workflow

After a loop completes, the experimental branch contains interleaved keep/discard commits. `autoresearch finalize <marker>` cleans this up:

```
FINALIZATION STEPS:
  1. Read results.tsv — identify all "keep" commits
  2. Group kept commits by logical change (based on description similarity)
  3. For each group:
     a. Create a clean branch from merge-base: autoresearch/<marker>-final-<N>
     b. Cherry-pick the relevant commits
     c. Squash into a single clean commit with combined description
  4. Output: list of final branches ready for review/merge

EXAMPLE:
  Input: autoresearch/auth-flow-mar30 (47 commits, 12 kept, 35 discarded)
  Output:
    autoresearch/auth-flow-final-1  "Add connection pooling" (+15% metric)
    autoresearch/auth-flow-final-2  "Simplify retry logic" (+3% metric, -20 lines)
    autoresearch/auth-flow-final-3  "Batch token refresh" (+7% metric)
```

CLI commands:
- Interactive: marker submenu → `[f] Finalize`
- Headless: `autoresearch --headless finalize --marker antoncore:auth-flow`

Finalization does NOT delete the original experimental branch — it creates new clean branches alongside it. The operator can review either.

### 4.13 Agent Invocation (NOT YET DESIGNED)
- How the LLM agent is actually called within the loop is TBD
- Options: Claude Code `-p` with generated program.md, Agent SDK, pluggable interface
- The engine needs to be agnostic about the agent runtime
- Agent receives: generated program.md containing mutable files list, immutable files (read-only context), metric info, results history
- Program.md is generated at runtime from the marker config -- NOT stored in the repo

---

## 5. Results (`.autoresearch/` in target repo)

### 5.1 Directory Structure

```
<target-repo>/
+-- .autoresearch/
    +-- <marker-name>/
    |   +-- results.tsv       # Experiment log
    |   +-- run.log           # Latest experiment output
    |   +-- ideas.md          # Ideas backlog + failure memory
    +-- <another-marker>/
        +-- results.tsv
        +-- run.log
        +-- ideas.md
```

### 5.2 results.tsv Format

Tab-separated, NOT comma-separated (commas break in descriptions).

```
commit	metric	guard	status	confidence	description
a1b2c3d	24	pass	keep	--	baseline
b2c3d4e	27	pass	keep	--	add retry logic to token refresh
c3d4e5f	25	pass	discard	--	remove error handling (regression)
d4e5f6g	0	--	crash	--	syntax error in auth.py
e5f6g7h	31	pass	keep	2.1	add connection pooling
f6g7h8i	33	fail	discard	--	aggressive caching (broke test suite)
g7h8i9j	32	pass	keep	2.4	batch token refresh
```

Columns:
1. `commit` -- short git hash (7 chars)
2. `metric` -- measured value from harness
3. `guard` -- guard result: `pass`, `fail`, or `--` (no guard / crash)
4. `status` -- `keep`, `discard`, `crash`, `refine`, `pivot`, or `needs_human`
5. `confidence` -- statistical confidence score (after 3+ keeps, else `--`)
6. `description` -- short text describing what the experiment tried

### 5.3 Persistence
- `results.tsv` is committed to the autoresearch branch
- Survives context resets -- the LLM agent reads it at the start of each experiment to understand history
- `run.log` is overwritten each experiment (only latest preserved)

---

## 6. Global State (`~/.autoresearch/`)

### 6.1 Directory Structure

```
~/.autoresearch/
+-- config.yaml               # Global defaults
+-- state.json                 # Tracked markers, runtime state
+-- daemon.pid                 # Daemon process ID
+-- daemon.log                 # Daemon output log
```

### 6.2 state.json Schema

```json
{
  "markers": [
    {
      "id": "antoncore:auth-flow-reliability",
      "repo_path": "/home/iamroot/dev/antoncore",
      "repo_name": "antoncore",
      "marker_name": "auth-flow-reliability",
      "status_override": null,
      "last_run": "2026-03-30T06:12:00Z",
      "last_run_experiments": 12,
      "last_run_kept": 8,
      "last_run_discarded": 4,
      "branch": "autoresearch/auth-flow-reliability-mar30",
      "baseline": 24,
      "current": 31,
      "worktree_path": null
    }
  ],
  "daemon": {
    "running": false,
    "pid": null,
    "started_at": null
  }
}
```

### 6.3 config.yaml Schema

```yaml
defaults:
  model: sonnet                    # Default LLM model for new markers
  budget_per_experiment: 10m       # Default time budget
  max_experiments: 50              # Default experiment cap
  direction: higher                # Default metric direction

daemon:
  poll_interval: 60s               # How often to check schedules
  max_concurrent: 2                # Max parallel marker runs
  log_level: info

notifications:
  # TBD -- plugin system or hardcoded channels
```

---

## 7. `/enhance-cli` Skill

### 7.1 Location
- Lives in `tcc-autoresearch/skills/enhance-cli/`
- Tested and perfected on this project's CLI
- Reusable -- can be copied to or referenced from any project

### 7.2 Purpose
Enforces two mandatory patterns on any CLI tool:

**Pattern 1: Interactive TUI (human mode)**
- Dynamic menus with numbered/lettered options
- Context-aware: detects CWD contents, shows relevant items
- Hover + action keys (e.g. `r` runs selected, `R` runs all in scope)
- Status indicators: `*` active, `o` skip, `#` paused, `=` completed
- Submenu navigation (select item -> deeper options)
- Auto-discovery (detect config files in CWD, prompt to register)

**Pattern 2: Headless mode (`--headless`)**
- Same functionality, zero interactivity
- All inputs via CLI flags -- no prompts, no confirmations
- JSON output to stdout, errors to stderr
- Exit codes: 0 success, 1 failure, 2 invalid input
- Documented for AI agent autonomous consumption
- Every prompted input has a corresponding `--flag`

### 7.3 Rule
Every feature MUST have both modes. If you build an interactive flow, you build the headless equivalent. No exceptions. The skill can be pointed at existing CLI code to audit and rewrite it into compliance.

### 7.4 Relationship to `headless-cli` Skill
The `headless-cli` skill in antoncore covers the `--headless` flag implementation pattern (Click helpers, JSON output, exit codes). `/enhance-cli` is broader -- it also enforces the interactive TUI design (menus, selections, action keys, auto-discovery). The two are complementary: `/enhance-cli` defines the full standard, `headless-cli` provides the implementation helpers for one half.

---

## 8. Program Template (Agent Instructions)

Each marker generates a `program.md`-style instruction document for the LLM agent. This is the equivalent of Karpathy's `program.md` but generalized.

### 8.1 Template Structure (draft)

```markdown
## Identity
You are an autonomous self-improvement agent.

## Scope
You may edit files in:
- <mutable_files from marker config>

You may NOT edit:
- <immutable_files from marker config>
- Any file outside the listed mutable set

## Metric
Run: <metric.command>
Extract: <metric.extract>
Objective: <metric.direction> is better
Baseline: <metric.baseline>
Target: <metric.target>

## Simplicity Criterion
A marginal improvement that adds complexity? Probably discard.
An equal result with less code? Definitely keep.

## Loop
1. Read current code and results.tsv history
2. Propose a hypothesis (what to change and why)
3. Edit target files
4. git commit with descriptive message
5. Run metric harness: <command> > run.log 2>&1
6. Extract result
7. If empty --> crash --> tail -n 50 run.log --> attempt fix or discard
8. Log to results.tsv
9. If improved --> KEEP (branch advances)
10. If equal or worse --> DISCARD (git reset --hard)
11. REPEAT -- NEVER STOP, NEVER ASK HUMAN

## Crash Handling
- Typo/syntax --> fix and retry (same experiment)
- Fundamental failure --> discard, log "crash", move on
- 3 consecutive crashes --> simplify back to last known good

## Time Budget
Each experiment must complete within <budget_per_experiment>.
If exceeded --> kill, treat as crash, discard.
```

### 8.2 Template Generation
- Engine generates this from the marker config at runtime
- Agent receives it as context/skill before the loop starts
- Template is NOT committed -- it's ephemeral, generated fresh each run

---

## 9. Execution Environments

### 9.1 Principle
The `.autoresearch.yaml` marker file makes any repo self-contained. Execution requires only:
1. The repo (cloned or checked out)
2. The `autoresearch` CLI installed in the environment
3. The LLM agent runtime (e.g. Claude Code) available

No payloads to construct, no configs to transfer, no integration code to maintain.

### 9.2 Local (default)
- Operator runs `autoresearch run -m <marker>` from terminal or daemon
- Engine reads marker from repo, creates worktree locally, runs loop locally
- LLM agent and harness commands execute on the local machine

### 9.3 Agenticore (deferred)
- Operator or AI agent dispatches: `run_task(repo_url=..., task="autoresearch run -m <marker> --headless")`
- Agenticore clones repo, `autoresearch` CLI reads marker from the cloned repo
- Agenticore does NOT need to understand autoresearch internals
- Prerequisite: `autoresearch` CLI pre-installed in agenticore container image or installed at task start

### 9.4 CI/CD (GitHub Actions, etc.)
- Workflow step: `run: autoresearch run -m <marker> --headless`
- Same pattern -- repo already checked out, CLI runs against it
- Useful for scheduled overnight runs or PR-triggered improvement loops

### 9.5 Any Remote Host
- `ssh server "cd /path/to/repo && autoresearch run -m <marker> --headless"`
- Only requirement: CLI + LLM runtime available on the host

### 9.6 CLI Packaging (for remote environments)
- Primary: `pip install tcc-autoresearch` (PyPI or private index)
- Container: pre-baked into execution container images
- Future consideration: single-file vendored script for zero-dependency bootstrap

---

## 10. Not Yet Designed

| Area | Open Questions |
|------|---------------|
| Agent invocation | Claude Code `-p`? Agent SDK? Pluggable adapter? |
| Notifications | Agnostic plugin system? Or explicit channel support (ntfy, email, Telegram)? |
| Discovery agent | Read-only scan that proposes marker configs for new targets? |
| Cost tracking | Per-marker cost accumulation? Budget enforcement across runs? |
| Multi-repo coordination | Run markers across repos in one daemon cycle? Priority ordering? |
| Auth for harnesses | How to handle harnesses that need credentials/API keys? |
| Worktree cleanup | Auto-remove after completion? Keep for review? Configurable? |
| Rollback depth | Can the agent rewind more than one experiment? How far back? |
| CLI distribution | PyPI package? Container image? Single binary? All three? |
| Agenticore image | Pre-install CLI in agenticore image, or install at task runtime? |
| Ideas backlog format | Should ideas.md support structured YAML frontmatter or stay pure markdown? |
| Confidence threshold | Should auto-merge require minimum confidence? What default? |
| Finalization grouping | Algorithm for grouping related commits — description similarity? File overlap? |
| SEARCH escalation | Which search sources? Web only? Or also scan related repos/docs? |
