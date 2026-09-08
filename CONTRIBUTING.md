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
- Test code is code. It gets the same style, the same naming care, and
  the same review as `src/`.
- Tests come in three layers, and the layer decides how a file is named
  and how much it explains. A healthy suite is a pyramid: many unit
  tests, fewer integration tests, fewest end to end tests. Each layer
  above catches what the one below cannot, and each costs more to run
  and more to keep working.
- [TESTING.md](TESTING.md) works through the layers with examples from
  this suite. The rules here are what review checks.
- Before adding a test, check its dependencies. Put isolated SDK and adapter
  tests in `surface/unit`, isolated Kyno module tests in `core/unit`, tests
  using multiple Kyno modules or a real store in `core/integration`, real
  client journeys in `core/e2e`, and repository checks in `checks`. See
  `TESTING.md` for examples.
- A unit test covers one module in isolation, and lives in
  `test_<module>.py`, one file per production module. The filename says
  what is covered, so the file needs no docstring.
- An integration test covers behavior that spans modules, and an end to
  end test walks a whole story through a running system. Both are named
  for the behavior rather than for a module, and both open with a
  one-line docstring saying what the file covers, because the filename
  cannot. These check the spec, not whether one component does its job.
- Keep commentary in tests to a minimum. Test functions need no docstring
  at any layer: the name says what is checked and the code says how. Test
  support code needs none either. Comment only what the code cannot say,
  like why a case exists at all.
- A test file reads: imports, then constants, then fixtures, then
  helpers, then tests. After the first test, everything is a test. A
  reader scanning for behaviors should not have to check whether a block
  of setup means the tests have ended.
- Support used by more than one file goes in `tests/`, imported by name
  (`tests/workspaces.py`, `tests/mcp_requests.py`). Fixtures shared
  across files go in `conftest.py`; plain helpers do not, because they
  arrive with no import and a reader cannot trace them. Support used by
  one test stays inside that test.
- Write deterministic tests. Run one twice and it gives the same result,
  and how fast the machine is must not change that. Real concurrency is
  fine where it proves a concurrency guarantee, as long as the assertion
  holds under every ordering.
- When the behavior you are testing relies on concurrency, keep two
  things in mind:
  - Don't use wait time as the success criteria. Whether the work
    finished within two seconds says more about the machine that ran it
    than about your code, so the answer changes between your laptop and
    a loaded CI runner.
  - Decide what happens when the work never finishes. A test with no
    answer for that hangs, reports nothing, and blocks CI until someone
    kills it.

## Pull requests

- A PR follows the Single Responsibility Principle: it changes one
  behavior and no more. If it does more than one thing, split it.
- A PR description covers three things: what it does, how to verify it,
  and where to look first.
- Follow the boy scout rule: leave the code better than you found it,
  tests included. If your change sits on top of something that needs
  cleaning up, like a helper that already exists elsewhere or a name that
  no longer matches what the code does, clean it up.
- When the cleanup introduces no behavior of its own, it can ride along
  in the same PR. Whether you keep it in its own commit is up to you.
- When the cleanup does introduce behavior, it should get its own PR,
  before or after yours, whichever you prefer. That way a reviewer
  approving your feature is not also approving a behavior change they did
  not come to review, and the cleanup gets the review a behavior change
  deserves.

## Licensing of new files

New files under `src/kyno/sdk/`, `src/kyno/adapters/`, or
`src/kyno/conformance/` start with the SPDX license line. Copy it from
any neighboring file; a test fails if it is missing. Files anywhere else
need no header.
