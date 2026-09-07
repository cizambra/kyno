# Contributing

Thanks for helping! These rules keep the codebase consistent. Anything
not listed here won't come up in review.

## Where writing goes

We document the project in four places. Each one answers a different
question. Before you write, decide which question you are answering, and
write it in that place.

- **Code comments** explain why we did something: a trade-off, a
  constraint, a surprising behavior kept on purpose. Don't use them to
  explain the mechanism, and don't describe what the next line does.
- **PR descriptions and design docs** explain the product change and the
  architecture decisions behind it. Keep them short. The code itself is
  the long-term record.
- **Tests** document how the system behaves right now. Each test covers
  one behavior and is named `given_{x}_when_{y}_then_{z}`. Test names
  describe the current state of the system; they never justify a change
  or mention removed features.
- **Docstrings** explain what a method does and what it returns in each
  case. Add a why only when you can't see it in the code, for example a
  rejected alternative, or something a library does that the code doesn't
  show. Don't add opinions like "best" or "cleaner".

## Code style

- Standard PEP 8, as `ruff`/`black` format it. No custom style rules.
- A comment is four lines or less.
- In tests, a comment like "Deliberate: …" marks behavior that is
  intentional and should not be changed casually. If you need to change
  it, say why in the PR.

## Tests

- Every change includes its tests in the same PR: tests for the new
  behavior, a test for each non-obvious decision, and, for bug fixes, a
  test that reproduces the bug before the fix.
- `python -m pytest -q` must pass. Postgres-specific tests run when
  `KYNO_TEST_POSTGRES_URL` is set and skip otherwise.
- A test file reads: imports, then constants, then fixtures, then
  helpers, then tests. After the first `def test_`, everything is a
  test. A reader scanning for behaviors should not have to check whether
  a block of setup means the tests have ended.
- Support used by more than one file goes in `tests/`, imported by name
  (`tests/workspaces.py`, `tests/mcp_requests.py`). Fixtures shared
  across files go in `conftest.py`; plain helpers do not, because they
  arrive with no import and a reader cannot trace them. Support used by
  one test stays inside that test.
- Write scripted, deterministic tests. A test may run real concurrency
  only to prove a concurrency guarantee, and its assertion must hold
  under every possible interleaving. Never use a fixed sleep to
  synchronize; wait on the task, event, or condition instead.

## Pull requests

- A PR follows the Single Responsibility Principle: it changes one
  behavior and no more. If a PR is doing more than one thing, it is
  doing too much; split it.
- A PR description covers three things: what it does, how to verify it,
  and where to look first.

## Licensing of new files

New files under `src/kyno/sdk/`, `src/kyno/adapters/`, or
`src/kyno/conformance/` start with the SPDX license line. Copy it from
any neighboring file; a test fails if it is missing. Files anywhere else
need no header.
