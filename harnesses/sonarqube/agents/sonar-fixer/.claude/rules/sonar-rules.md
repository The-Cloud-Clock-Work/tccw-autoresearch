# SonarQube Fix Rules

- Never suppress issues with comments (`# noqa`, `// NOSONAR`, `@SuppressWarnings`)
- Never move code around just to avoid detection — fix the actual issue
- For Python bugs: check for None checks, unreachable code, wrong types, resource leaks
- For Python code smells: reduce cognitive complexity, remove unused imports/variables, fix naming
- For security vulnerabilities: fix the actual vulnerability, do not just add validation theater
- One commit per issue fix — atomic changes only
- Commit message format: `fix(sonar): <rule-key> in <filename>`
