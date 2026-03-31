# Simplify Test

Review a test file for redundancy, clarity, and efficiency.

## Steps

1. Read the target test file
2. Identify:
   - Duplicate test cases that cover the same code path
   - Overly complex test setups that can be simplified
   - Missing assertions (tests that run but don't verify behavior)
   - Dead test code (helper functions never called)
3. Simplify without reducing coverage
4. Run pytest to verify nothing broke
