# TODO.md -- Minor Items & Don't Forget

> **Purpose:** Small items, notes, and things to not forget. Not major blocks — those go in `BLOCKS.md`. This is the scratchpad for details that would otherwise be lost between sessions.

---

## Pending Decisions

- [x] CLI framework: `typer` — entry point `cli:app` matches naturally, less boilerplate (resolved Block 3)
- [x] TUI rendering: `rich` — tables + panels + prompts, textual overkill for action-key menus (resolved Block 3)
- [x] Git operations: subprocess calls (**decided** — simpler, fewer deps, works everywhere)
- [x] Marker file name confirmed: `.autoresearch.yaml`
- [x] Results dir confirmed: `.autoresearch/`
- [x] Agent invocation: ABC interface (`AgentRunner`), `ClaudeCodeRunner` wraps `claude -p`
- [x] Program template: Python string constant, no Jinja dependency
- [x] Escalation state: in-memory per run, not persisted to state.json

## Notes from Build Sessions

- 2026-03-30: Block 2 (Engine) completed. 4 modules: worktree.py (git isolation), metrics.py (harness + confidence), program.py (template gen), engine.py (loop + escalation + agent ABC). 105 new tests, 143 total. No new dependencies.

## Notes from Design Sessions

- 2026-03-30: Research sweep (2 agents, 30+ repos, HN/Reddit/Medium/YouTube/GitHub). 5 features adopted: ideas backlog, graduated escalation, statistical confidence, dual-gate guard, finalization workflow. All added to SPECS.md and VISION.md.
- 2026-03-30: Karpathy repo analysis — zero dependency, methodology only. 6 files, 1252 lines, all ML-specific. Nothing to import.
- 2026-03-30: Execution model resolved — repo is self-contained. CLI reads marker from repo. Any system that runs `autoresearch run -m <marker> --headless` in a cloned repo is an executor. No adapters, no plugins, no special payloads.
- 2026-03-30: Agenticore integration = just `run_task(task="autoresearch run -m X --headless")`. Agenticore doesn't need to understand autoresearch.
- 2026-03-30: `/enhance-cli` skill created in cc-colt-tools (was planned for this repo, moved to portable location). Enforces interactive TUI + headless dual-mode on any CLI
- 2026-03-30: Name collision — 323+ repos use "autoresearch" on GitHub. Our repo: `tcc-autoresearch`

## Don't Forget

- [x] `autoresearch` CLI must be pip-installable for remote execution environments
- [x] Dogfood: `.autoresearch.yaml` in this repo itself for self-improvement
- [x] Program template generated at runtime from marker config — NOT stored in repo
- [x] Local status override (state.json) takes precedence over YAML status
- [x] Marker ID format: `repo_name:marker_name` — handle dir name conflicts with full path fallback
