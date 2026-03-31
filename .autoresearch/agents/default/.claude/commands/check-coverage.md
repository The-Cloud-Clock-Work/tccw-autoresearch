---
description: Analyze test coverage gaps in the mutable files
allowed-tools: [Bash, Read, Grep, Glob]
---

Analyze test coverage for the mutable files:

1. Run `python3 -m pytest --cov --cov-report=term-missing` if pytest-cov is available
2. If not, read the test files and source files, identify untested functions
3. Report which functions/branches have no test coverage
4. Suggest the highest-impact tests to add next
