# Contributing

Thanks for helping! A few essentials keep the codebase consistent — anything
not listed here is not a review nit.

## Code style

- Standard PEP 8, as `ruff`/`black` format it. No custom style rules.
- **Code should explain itself.** Write a comment only for something the code
  cannot say — a deliberate trade-off, a non-obvious constraint, a surprising
  behavior kept on purpose — and keep it to four lines or less. Never comment
  what the next line does.
- In tests, the test name and its assertions are the documentation. A comment
  like "Deliberate: …" marks behavior that is intentional and should not be
  changed casually — if you need to change it, say why in the PR.

## Tests

- Every change ships with its tests in the same PR: tests for the new
  behavior, a test for each non-obvious decision you made along the way, and
  — for bug fixes — a test that reproduces the bug before the fix.
- `python -m pytest -q` must pass. Postgres-specific tests run when
  `KYNO_TEST_POSTGRES_URL` is set and skip otherwise.
- Prefer scripted, deterministic tests. A test may exercise real concurrency
  only to prove a concurrency guarantee, and its assertion must hold under
  every possible interleaving. Never use a fixed sleep as a synchronization
  point — await the task, event, or condition itself.

## Pull requests

- Keep PR descriptions short: what it does, how to verify, where to look.
  The durable explanation belongs in the code and commit messages.

## Licensing of new files

New files under `src/kyno/sdk/`, `src/kyno/adapters/`, or
`src/kyno/conformance/` start with the SPDX line — copy it from any
neighboring file; CI reminds you if you forget. Files anywhere else need no
header.
