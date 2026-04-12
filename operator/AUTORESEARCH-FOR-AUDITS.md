# AutoResearch for Audits — Analysis & Application Framing

> **Author:** publisher agent (analysis pass for Nestor)
> **Date:** 2026-04-12
> **Status:** Analysis only — no artifacts, no demo. Pickup point for tomorrow.
> **Scope:** Deep read of `tccw-autoresearch` (VISION, SPECS, BLOCKS, source). Frames the implementation along four axes: power, agnosticism, agentic-RL fit, and **diagnosticity**. Closes with a light Schroders/audit-score application sketch.

---

## 0. TL;DR

`tccw-autoresearch` is a clean-room generalization of Karpathy's overnight loop into a production CLI/daemon. Karpathy proved the recipe on one file (`train.py`) and one metric (`val_bpb`). You stripped the ML, kept the loop, and turned the **marker file** into the universal interface between "here is something I want better" and "here is an autonomous improvement run."

Four properties make it interesting beyond the original:

1. **Power** — graduated escalation, dual-gate verification, statistical confidence, ideas-backlog memory, and finalization workflow turn a dumb hill-climber into a research process that compounds.
2. **Agnosticism** — the engine knows files, metrics, git, and loops. Nothing else. The repo is the unit of execution; the marker is the unit of intent; the CLI is the only interface. No stack assumptions, no integration layer.
3. **Agentic-RL fit** — the loop **is** RL with a scalar reward, an immutable environment, a recoverable state (git), and a policy expressed as code edits. When the *target itself is an agent profile* (settings.json, CLAUDE.md, MCP allowlist, prompt rules), you get RL applied to agentic engineering inside the same source code that drives the agent. Recursive self-improvement with a hard safety floor (immutable harness).
4. **Diagnosticity** — and this is the part that matters most for audits: every run is an *experiment in differential pressure*. The metric tells you the score, but the **trajectory** (kept vs. discarded vs. crashed vs. guard-failed vs. needs-human) tells you where the codebase is brittle, where it's noisy, where it's load-bearing, and where it's actually broken. The loop is an instrument before it is an optimizer.

The Schroders audit framing falls out naturally: an audit is a measurement function (audit score) over a target (a controlled system, a process, a codebase, a document corpus). If the score is mechanically extractable, autoresearch can drive it up — and the *trajectory* gives you the audit narrative for free.

---

## 1. The implementation in one diagram

```
.autoresearch/config.yaml
    declares: target.mutable, target.immutable, metric, guard,
              agent, escalation, schedule, results
        |
        v
autoresearch CLI
    interactive TUI  ||  --headless JSON mode
        |
        v
git worktree per marker
    branch: autoresearch/<marker>-<date>
        |
        v
The Loop (engine.py)
    1. Read code + results.tsv + ideas.md (failure memory)
    2. Agent proposes hypothesis
    3. Agent edits MUTABLE files only (settings.json deny enforces it)
    4. git commit
    5. Run metric.command -> extract single number
    6. Gate 1: improved? --no--> DISCARD (git reset)
                 |
                 yes
                 v
    7. Gate 2: guard.command passes? --no--> REWORK xN
                 |                       |
                 yes                     still fails
                 v                       v
               KEEP                    DISCARD
    8. Append row to results.tsv (commit, metric, guard,
       status, confidence, description)
    9. Compute MAD-based confidence after 3+ keeps
   10. Discarded? Agent writes WHY to ideas.md

Failure escalation:
    3 fails  -> REFINE  (retune within current approach)
    5 fails  -> PIVOT   (abandon approach, new direction)
    2 PIVOTs no progress -> SEARCH (external web research)
    3 PIVOTs total       -> HALT   (status: needs_human, notify)
        |
        v
autoresearch finalize <marker>
    cherry-pick the kept commits, group by logical change,
    squash into clean reviewable branches.
```

The whole thing is six modules: `marker`, `state`/`config`, `results`/`ideas`, `engine`/`worktree`/`metrics`/`program`, `cli`/`finalize`, `daemon`. Plus `agent_profile` and `telemetry` as the hard safety/observability layer.

---

## 2. What makes it powerful

Karpathy shipped the *recipe*. You shipped the *process*. The delta is what makes it usable as something other than a science demo.

### 2.1 Failure memory (ideas.md) — the loop compounds across sessions

A naive hill-climber forgets. It will re-try the same discarded direction next week because the only persistent state is the commit history of *kept* changes. You log discarded-but-promising directions, near-misses, and external research findings into `.autoresearch/<marker>/ideas.md`, and the agent reads it at the start of every experiment. Two consequences:

- **No re-treading.** "Connection pooling broke thread safety at exp #12" stays remembered. Next session, the agent either avoids it or comes back armed.
- **Compounding hypothesis quality.** Near-misses become starting points. The space of explored ideas grows monotonically even as the kept branch ratchets.

This is the difference between a stochastic optimizer and something that resembles a research notebook.

### 2.2 Graduated failure escalation — the loop knows when it's stuck

A flat circuit breaker ("crash 3 times, stop") wastes the autonomous-overnight property. Your escalation ladder turns "stuck" into a state machine:

| State | Trigger | Behavior |
|-------|---------|----------|
| normal | 0–2 consecutive fails | retry with new hypothesis |
| REFINE | 3 fails | retune within current approach, re-read ideas.md |
| PIVOT | 5 fails | abandon current approach entirely, pick a new direction |
| SEARCH | 2 PIVOTs without progress | external web research, append to ideas.md |
| HALT | 3 PIVOTs total | mark `needs_human`, notify, stop |

Each state is a *different* prompt-time strategy, not just a retry. The agent doesn't burn budget grinding on the same dead end. It reorganizes.

### 2.3 Dual-gate verification (guard) — can't game the metric

Single-metric optimization is exploitable. The agent will find a way to game the specific metric while breaking everything else (the LLM equivalent of reward hacking). Your guard command is a separate immutable harness — typically a broader test suite — and is wired in as Gate 2:

```
metric improved? --yes--> guard passes? --yes--> KEEP
                              |
                              no
                              v
                          REWORK xN (agent reads guard output, attempts fix)
                              |
                              still fails
                              v
                            DISCARD
```

This is structurally why the loop can run on production code without a human in the loop. The metric is the carrot; the guard is the floor. The agent can move freely above the floor, never below.

### 2.4 Statistical confidence (MAD) — distinguishes signal from noise

A jump from 24 -> 25 might be benchmark variance. A jump from 24 -> 31 is real. After 3+ kept experiments, the engine computes confidence as `|current - baseline| / (MAD * 1.4826)`. >=2.0 = high, 1.0–2.0 = medium, <1.0 = noise. **It does not gate the loop** — it informs the operator at merge time and (future) gates auto-merge. This is the difference between "the agent thinks it improved" and "the improvement survives a noise test."

Critically: this is the only place statistics enter the loop. No Bayesian gymnastics, no CI math the operator has to interpret. One scalar, three colors.

### 2.5 Finalization — the messy branch becomes a reviewable PR

After 100 experiments, the autoresearch branch is 47 commits of interleaved keep/discard/crash. Useless for review. `autoresearch finalize` reads results.tsv, identifies the kept commits, groups them by logical change, and produces clean squashed branches:

```
autoresearch/auth-flow-final-1  "Add connection pooling"   (+15% metric)
autoresearch/auth-flow-final-2  "Simplify retry logic"     (+3%, -20 lines)
autoresearch/auth-flow-final-3  "Batch token refresh"      (+7% metric)
```

Without this step, the loop produces work that nobody wants to merge. With it, the output is a stack of small, attributable, mergeable improvements — the format a human reviewer expects.

### 2.6 Hard permission enforcement (Block 5) — safety is structural, not norm-based

Most agent runners rely on prompt instructions to keep the agent in scope ("do not edit these files"). You enforce it via Claude Code's `dontAsk` permission mode: the engine generates `settings.json` per marker at runtime, putting `Edit(<mutable>)`/`Write(<mutable>)` in `permissions.allow`. Anything else — including the metric harness, the guard harness, and the entire rest of the repo — is **auto-denied at the tool layer**, not at the prompt layer.

This is the single most important security decision in the whole system. The agent *cannot* edit the harness even if it tries. The immutability of the metric is enforced by the runtime, not by the agent's good behavior. This is what makes the loop production-runnable.

### 2.7 Telemetry — every run is observable

`telemetry.py` parses the agent's `--output-format stream-json` into a `TelemetryReport`: tokens, cost, tool calls, errors, denials. Errors and permission denials get fed back into ideas.md as a feedback loop — the agent's failures become inputs to the next session's hypotheses.

This is what makes the loop *legible*. After a 100-experiment overnight run, you don't just have a number; you have the full causal trace.

---

## 3. What makes it agnostic

Karpathy's autoresearch is `train.py` + `prepare.py` + `program.md`. Everything else is hardcoded. Every fork (`autoresearch-macos`, `autoresearch-mlx`, `autoresearch-win-rtx`) just re-hardcodes a different ML stack. None of them generalized the *algorithm*.

You generalized the algorithm. The five decisions that did it:

### 3.1 The marker file is the only contract

`.autoresearch/config.yaml` declares everything: what's mutable, what's immutable, how to measure, how to guard, how to escalate, how to schedule. The engine has zero knowledge of *what* it's improving. It knows: "run this command, parse this regex, larger is better, baseline is 24, target is 34." That's the entire interface.

This means autoresearch works on:

- Application code (any language — the harness is shell)
- Infrastructure code (Helm values, Dockerfiles, k8s manifests)
- Configs (LiteLLM YAML, prompt files, agent settings.json)
- Documents (any artifact whose quality is mechanically scored — coverage %, lint score, audit score, **score from a checklist evaluator**)

Nothing in the engine assumes Python, ML, tests, or even code. It assumes "shell command -> number."

### 3.2 The repo is the unit of execution, not a payload

This is the architectural decision the rest of the system rests on. There is **no payload format**. There is no "autoresearch task descriptor" that gets serialized and shipped to a remote runner. The repo carries the marker, the CLI reads the marker from the repo, the loop runs in a worktree of that same repo. Every execution environment looks identical:

```bash
# local
autoresearch run -m auth-flow

# agenticore
run_task(repo_url=..., task="autoresearch run -m auth-flow --headless")

# GitHub Actions
run: autoresearch run -m auth-flow --headless

# cron on any box
0 1 * * * cd /repo && autoresearch run -m auth-flow --headless
```

**Zero adapters. Zero integration code.** Any runner that can `git clone` and execute a shell command is an autoresearch runner. This is what the VISION calls "no executor abstraction layer." It's the strongest property of the design — it makes all future execution backends free.

### 3.3 Dual-mode CLI (`/enhance-cli`) — same surface for human and machine

Every command works interactively (TUI, menus, action keys) and headlessly (`--headless`, JSON, exit codes 0/1/2). This is enforced as a build-time discipline via the `/enhance-cli` skill — no command can ship without both modes.

The consequence: the same CLI is the operator interface, the agent interface, the CI interface, and the cron interface. There is no "API" beneath the CLI. The CLI **is** the API.

### 3.4 Pluggable agent runner (ABC) — Claude Code is one implementation

`AgentRunner` is an abstract base class. `ClaudeCodeRunner` is the first implementation. The engine talks to the ABC. Any future runner — Codex, Gemini, a local OSS agent, a different orchestrator — slots in by implementing the same interface. This isn't plumbing; it's the only place the loop touches the LLM, so isolating it cleanly is what keeps the rest of the engine pure.

### 3.5 Self-contained agent profile per marker

`agent_profile.py` generates `settings.json` and `CLAUDE.md` at runtime from the marker config. Different markers can run with different models, different effort levels, different tool allowlists, different system prompts. The marker file is a **complete description of an autonomous research project**, not just a target file list. That's what lets you say "this marker uses opus + extended thinking + only Edit/Write/Read/Bash(pytest:*)" and have it Just Work.

---

## 4. Why this is the best fit for agentic RL applied to agentic engineering

This is the part that matters most for the long-term play. Three claims:

### 4.1 The loop is structurally RL

| RL concept | autoresearch instantiation |
|------------|-----------------------------|
| Environment | the codebase under git, the harness, the guard |
| State | git HEAD + results.tsv + ideas.md |
| Action space | file edits within `target.mutable` |
| Policy | the LLM agent conditioned on program.md + history |
| Reward | `metric.extract` output (scalar) |
| Episode | one experiment (edit -> commit -> run -> measure -> keep/discard) |
| Episode termination | budget exhausted, target reached, or HALT |
| Replay buffer | results.tsv (kept commits as positive examples) |
| Counterfactual memory | ideas.md (discarded directions, near-misses) |
| Safety constraint | dual-gate guard + immutable harness + dontAsk perms |

The loop is RL **without the gradient**. The policy is updated implicitly: each experiment's history is part of the next experiment's prompt context, so "learning" happens via in-context conditioning across the results.tsv + ideas.md ratchet. You don't need backprop because the policy is a frozen LLM and the "weights" being updated are the discovered code state and the failure memory.

What makes this *better* than classical RL for agentic engineering:

- **No reward hacking floor.** Immutable harness + guard = the agent can't exploit the environment at the runtime level.
- **Explainable rollback.** Every "weight update" is a git commit. Every regression is a `git reset --hard`. There is no opaque parameter shift.
- **Cross-session compounding.** ideas.md is a literal text replay buffer. The agent reads it, reasons over it, and writes to it. No vector store, no embedding model, no retrieval magic — just markdown the agent can grep.

### 4.2 The same source code can be the *agent* and the *target*

This is the recursive insight. Most RL-on-LLMs work treats the agent as the policy and *something else* as the environment. Autoresearch lets you point the agent at its own configuration:

```yaml
markers:
  - name: agent-self-improvement
    target:
      mutable:
        - .autoresearch/agents/default/CLAUDE.md
        - .autoresearch/agents/default/settings.json
        - .autoresearch/agents/default/rules/*.md
      immutable:
        - tests/test_agent_smoke.py
        - tests/benchmark_agent_quality.sh
    metric:
      command: "python tests/benchmark_agent_quality.py"
      extract: "grep -oP 'score: \\K[\\d.]+'"
      direction: higher
```

Now the loop is editing the agent's own profile, prompt rules, and tool allowlist, and the metric is "how well does this agent perform on a fixed evaluation suite." This is **agentic RL inside agentic engineering** — the same source code (`tccw-autoresearch`) hosts both the policy-improvement loop and the policy being improved, with the immutable harness preventing the agent from rewriting its own evaluation.

A cleaner statement of the property: *the engine is invariant under the choice of target, including when the target is the engine's own agent configuration*. There is no Anton-special-case, no MCP-special-case, no agent-special-case. It just falls out of the marker abstraction.

### 4.3 The safety floor makes recursive self-improvement actually safe

The classical concern with self-improving agents is that they game the eval. The classical answer is "make the eval immutable." Most attempts at this rely on prompt instructions ("do not edit these files"), which the agent will eventually violate.

Your answer is the runtime permission system. `target.immutable` is enforced via Claude Code's `dontAsk` mode: the harness files, guard files, and everything outside `target.mutable` are *physically not editable* by the agent's tool layer. The agent's intent is irrelevant. It cannot reach those files.

This is the structural property that makes recursive self-improvement of agent profiles a tractable problem instead of a science-fiction one.

---

## 5. Diagnosticity — the loop as an instrument

This is the section that matters most for audits. Read carefully.

The framing change: **autoresearch is not (just) an optimizer. It is a differential pressure instrument.** Every experiment is a probe. Every keep/discard/crash/guard-fail/needs-human outcome is a signal about the *target system*, not just about the agent's progress.

### 5.1 What the trajectory tells you

After a single overnight run, results.tsv contains 50–100 rows. The *number* the metric reaches is one piece of information. The *shape* of the trajectory is much richer. Here's what each pattern means as a diagnostic signal:

| Pattern in results.tsv | What it tells you about the target |
|------------------------|------------------------------------|
| Long flat plateau then sudden jump | A load-bearing constraint was discovered and removed. Worth a postmortem — that constraint may exist elsewhere. |
| Many small keeps, no big jumps | The system is well-tuned; remaining gains are incremental. Confidence will be low. Stop early. |
| Frequent guard failures on metric improvements | The metric is **decoupled from quality** — the agent can move it without moving the underlying property. The metric is wrong. |
| Frequent crashes on syntactically simple changes | The system is brittle to perturbation. There is hidden coupling. This is an architectural smell, independent of the metric. |
| High variance between adjacent kept experiments | Benchmark noise dominates. Confidence will be low. The harness needs hardening before optimization is meaningful. |
| Repeated PIVOTs without progress | The metric has hit a ceiling that cannot be moved by changes to `target.mutable`. The bottleneck is **outside the mutable set** — i.e., the *operator* drew the wrong boundary. |
| ideas.md fills with "guard failed for thread-safety reasons" | A class of risk concentrates around concurrency. Audit finding, not just an optimization observation. |
| External SEARCH escalation triggers | The local hypothesis space is exhausted. Whatever you're improving is in well-explored territory. |
| HALT with `needs_human` after PIVOT exhaustion | The improvement target is incoherent with the target codebase. Either the metric is wrong, the immutable boundary is wrong, or the system is fundamentally not improvable along this axis. **This is itself a high-value finding for an audit.** |

In every row of that table, the loop is acting as a diagnostic instrument. The "score went up" is incidental. The **structure of the failures and the geometry of the trajectory are the audit narrative**.

### 5.2 Why the design choices already make it diagnostic

You didn't build it for audits. But every intelligence feature is also a diagnostic feature, by accident or by good taste:

| Feature | Optimization role | Diagnostic role |
|---------|------------------|-----------------|
| Dual-gate guard | Prevents reward hacking | Reveals **decoupling between metric and quality** |
| MAD confidence | Filters noise | Quantifies **harness reliability** |
| ideas.md | Avoids re-trying failures | Catalogues **classes of failure mode** |
| Graduated escalation | Recovers from stuck loops | Marks **complexity boundaries** of the system |
| Crash detection | Discards broken experiments | Maps **fragility surface** of the codebase |
| Telemetry (denials, errors) | Debug the agent | Maps **scope leakage attempts** — what the agent *wanted* to touch outside the mutable set |
| Finalization grouping | Produces reviewable PRs | Reveals **logical clusters** in the change space — natural decomposition of the problem |

The loop runs forward on optimization and *backward* on diagnostics, simultaneously, from the same data. You get both for the price of one. This is what the document title means by **diagnosticity**: the property that the same instrument that improves a system also produces a structured account of what was wrong with it.

### 5.3 Diagnosticity as a first-class output

For audit applications, this needs to be elevated from a side-effect to a first-class output. Today, results.tsv + ideas.md + telemetry contain everything an audit narrative needs — but the operator has to read them. A future block (call it Block 7: Audit Reporter) would post-process a finished run into a structured report:

```
AUDIT REPORT — antoncore:auth-flow-reliability
================================================
Score:           24 -> 31 (+29%)
Confidence:      2.4x MAD (high)
Experiments:     47 (12 kept, 28 discarded, 5 crashed, 2 guard-failed)

FINDINGS
  [F1] Load-bearing constraint removed at exp #15 (connection pooling)
       -> Likely exists in other auth flows. Recommend audit.
  [F2] Metric decoupled from quality at exp #22, #29, #34
       -> Three guard failures on metric improvements. Metric needs review.
  [F3] Concurrency fragility (5 ideas.md entries flagged thread-safety)
       -> Class of risk. Recommend concurrency review beyond this marker.
  [F4] HALT not reached, but escalation triggered REFINE 3x and PIVOT 1x
       -> System is improvable but constrained. Bottleneck at exp #33–41.

CHANGE CLUSTERS (from finalization)
  C1: Connection pooling     (+15%, exp #15)
  C2: Retry simplification   (+3%, -20 lines, exp #22)
  C3: Token refresh batching (+7%, exp #41)
```

This is the artifact format an auditor wants. Today it's reconstructable from the raw files. Tomorrow it could be one CLI command.

---

## 6. Schroders / audit-score application (light sketch — not the demo)

Holding to the operator instruction: **do not go deep on Schroders yet, do not build artifacts**. This section frames the path so tomorrow's pickup is unambiguous.

### 6.1 The shape of an audit-score marker

Schroders audits produce a numerical score over a controlled object — process docs, control evidence, configuration baselines, code/infrastructure compliance, whatever the audit unit is. If that score is mechanically extractable (a checklist evaluator, a rubric script, a parser over a controlled corpus), it fits the marker contract directly:

```yaml
markers:
  - name: control-evidence-uplift
    description: Increase audit score on the [redacted] control set
    target:
      mutable:
        - controls/<scope>/**          # the artifacts being uplifted
      immutable:
        - audit/scoring_rubric.py      # the rubric is the harness — never touched
        - audit/regression_checks.py   # guard
    metric:
      command: "python audit/scoring_rubric.py controls/<scope>/"
      extract: "grep -oP 'score: \\K[\\d.]+'"
      direction: higher
      baseline: <measured>
      target: <target score>
    guard:
      command: "python audit/regression_checks.py controls/<scope>/"
      extract: "grep -oP '(\\d+) passed'"
      threshold: <full pass count>
      rework_attempts: 2
    agent:
      model: opus
      budget_per_experiment: 8m
      max_experiments: 60
```

Three things to note:

1. **The rubric is the harness.** It must be deterministic, reproducible, and immutable during the run. If the audit rubric is a human judgment call, it has to be wrapped in a deterministic scorer first — that scoring step is its own pre-work.
2. **The guard is a regression check** — typically "no previously-passing controls now fail." This is the structural defense against gaming the score.
3. **The mutable set is the audit object**, not the scoring code. The agent uplifts evidence; it does not edit the rubric.

### 6.2 Where the diagnosticity becomes the deliverable

For Schroders specifically, the *trajectory* is more valuable than the score. An audit isn't only "did the score go up?" — it's "what did we learn about the control set?" The diagnosticity table in §5.1 maps directly to audit findings:

- guard failures -> controls where evidence and underlying behavior are decoupled
- crashes -> fragile controls that break under perturbation
- PIVOT exhaustion -> controls that cannot be uplifted along this axis (architectural finding)
- ideas.md clusters -> classes of weakness across the control set
- finalization clusters -> natural groupings of remediation work

The "Block 7: Audit Reporter" sketch in §5.3 is what tomorrow's session probably wants to converge on — turning the side-effect diagnostic data into a first-class audit artifact format.

### 6.3 Translation work that has to happen first (not today)

For Schroders consumption, the vocabulary needs to be translated: marker -> "audit run," metric -> "audit score," guard -> "regression check," `target.mutable` -> "in-scope artifacts," `target.immutable` -> "scoring rubric," ideas.md -> "findings backlog," finalization -> "remediation plan." The technical contract is unchanged; only the names move.

This is the "high-level table Francisco asked for" angle from the prior session. It's a translation pass over the terminology, not a new system. **Do not start it yet** — the operator has explicitly held this for tomorrow.

---

## 7. Open questions for tomorrow's pickup

These are the threads to pull on next, in priority order:

1. **What does Schroders' audit score look like as a shell command?** Concretely: is there a script that takes a directory of evidence and emits a single number? If not, the first block of work is wrapping the human-judgment audit rubric in a deterministic scorer. Without that, no marker is possible.
2. **What is the immutable set for an audit run?** The rubric, definitely. What else? Reference baselines? Historical evidence? The guard surface needs to be drawn.
3. **What is the guard?** "Score went up" alone is not safe for audit work — the agent will find ways to satisfy the rubric without satisfying the underlying intent. The guard has to be a separate broader check.
4. **Block 7: Audit Reporter** — should the diagnosticity post-processor be its own block, or folded into a `--report` flag on existing commands? My read: own block, because the report format is the *deliverable* for audit clients and deserves its own design pass.
5. **Vocabulary mapping table** — translate marker/metric/guard/ideas.md/finalization into audit-speak as a one-page reference. This is the "Francisco table." Trivial once the technical model is agreed.
6. **Sandboxing the harness** — for Schroders, the harness will likely run on sensitive data. The dontAsk permission model handles file access but not network egress. Worth confirming what the harness is allowed to touch.
7. **Confidence threshold for audit acceptance** — the SPECS leaves "minimum confidence for auto-merge" as TBD. For audit work, this is not optional — a low-confidence score uplift should never auto-publish. Probably >=2.0 MAD.

---

## 8. The one-line summary

> **autoresearch is an instrument that improves systems by probing them, and the probe trace is itself the audit. The Schroders work is not "use autoresearch for audits" — it is "expose the diagnostic trace autoresearch already produces, in a vocabulary an auditor can read."**

That is the thing to build, when it's time to build it.

---

*End of analysis. No artifacts created. Pickup tomorrow at §7 question 1.*
