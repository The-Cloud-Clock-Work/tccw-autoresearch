# Testing

> Test suite, fixtures, running tests.

## Running Tests

```bash
# All tests
pytest

# Single module
pytest tests/test_engine.py

# With coverage
pytest --cov=autoresearch
```

## Test Files

| Test File | Covers |
|-----------|--------|
| `test_cli.py` | CLI commands and output modes |
| `test_engine.py` | Core experiment loop |
| `test_marker.py` | YAML parsing and schema validation |
| `test_metrics.py` | Metric extraction and guards |
| `test_state.py` | State persistence and overrides |
| `test_worktree.py` | Git worktree operations |
| `test_daemon.py` | Daemon scheduling |
| `test_results.py` | Results tracking |
| `test_ideas.py` | Idea generation |
| `test_program.py` | Program synthesis |
| `test_config.py` | Configuration loading |
| `test_finalize.py` | Finalization flow |
| `test_telemetry.py` | Telemetry tracking |
| `test_utils.py` | Utility functions |
| `test_cli_utils.py` | CLI helper functions |
| `test_agent_profile.py` | Agent profile loading |

## Fixtures

Shared fixtures are in `tests/fixtures/`: sample marker YAML files (`valid_marker.yaml`, `minimal_marker.yaml`, `invalid_marker.yaml`) and a stream-json sample (`stream_json_sample.jsonl`).
