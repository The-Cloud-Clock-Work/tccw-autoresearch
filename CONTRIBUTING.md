# Contributing to AutoResearch

Thanks for your interest in contributing to AutoResearch.

## Prerequisites

- Python 3.10+
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) installed and authenticated
- Git

## Setup

```bash
git clone https://github.com/The-Cloud-Clockwork/tcc-autoresearch.git
cd tcc-autoresearch
pip install -e ".[dev]"
```

## Running Tests

```bash
pytest tests/ -q
```

## Code Quality

```bash
ruff check src/ tests/
```

We use [SonarQube](https://sonarcloud.io) for continuous inspection. All PRs must pass the quality gate (0 bugs, 0 vulnerabilities, no new code smells).

## How to Contribute

1. Fork the repo
2. Create a feature branch from `main`
3. Make your changes
4. Run tests and linting
5. Open a PR against `main`

## What to Contribute

- **New metric harnesses** — common `metric.command` + `metric.extract` recipes for popular tools
- **Bug fixes** — check [issues](https://github.com/The-Cloud-Clockwork/tcc-autoresearch/issues)
- **Documentation** — improvements to docs, examples, tutorials
- **Agent profiles** — custom agent configurations for specific use cases

## Code Style

- We use `ruff` for linting
- Type hints on public function signatures
- `pathlib.Path` over `os.path`
- f-strings over `.format()`

## Commit Messages

- Imperative mood: "fix bug" not "fixed bug"
- Prefix: `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
