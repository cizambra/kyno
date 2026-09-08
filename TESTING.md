# Testing Kyno

For contributors. [CONTRIBUTING](CONTRIBUTING.md) holds the rules a
reviewer will hold you to; this page explains how to apply them, with
examples from the suite. If the two ever disagree, CONTRIBUTING wins.

One thing before the rest: test code is still code. It gets read more
often than the code it covers, usually by someone deciding whether a
change is safe, and it is the executable description of what the system
does. Much of this page asks you to write less in a test. That is not
because tests matter less. It is because the names and the code then have
to carry the meaning on their own, which is a harder standard than a
comment, not an easier one.

## Three layers

A test belongs to exactly one layer, and the layer decides where it
lives, what it is called, and how much it explains.

**Unit.** Covers one production module in isolation. Lives in
`tests/core/unit/test_<module>.py` or
`tests/surface/unit/test_<module>.py`, one file per module. For example,
`src/kyno/profiles.py` is tested by `tests/core/unit/test_profiles.py`,
while SDK cells are tested by `tests/surface/unit/test_cell.py`. The
filename already says what is covered, so the file needs no docstring.

**Integration.** Covers behavior that spans modules. `test_concurrency.py`
in `tests/core/integration/` checks that exactly one writer wins a race,
which no single module guarantees on its own: it falls out of the store,
the service, and a database constraint together. Named for the behavior,
because no module name would be honest.

**End to end.** Walks a whole story through a running system.
`tests/core/e2e/test_deployment_e2e.py` creates a workspace, starts a real
`kyno serve` process, mints tokens, reads, gets refused, writes, and
revokes, using the commands a person would type. These check the spec:
what an operator can do, in order.

Aim for a pyramid. Most tests are unit tests, fewer are integration
tests, fewest are end to end. Each layer above catches what the one below
cannot, and each costs more to run and more to keep working. A failing
unit test names the module; a failing end to end test says something in a
six-module chain broke, and you still have to go find it.

## Choosing a layer

Ask what would have to break for this test to fail.

If the answer names one module, it is a unit test. If it names two or
more, it is an integration test, even when the test reads like it is
about one of them. If it names the whole running system, including a
process or a socket, it is end to end.

One case trips people up: **importing several modules does not make it
an integration test.** `test_sql_store.py` imports the models and the
errors because the store returns those types. It still fails for one
reason, which is that the store is wrong.

## Isolation and mocks

A unit test isolates its module, and mocking the collaborators is how you
get there. That buys three things: the test runs fast, its setup states
plainly what the module expects from the code around it, and a failure
names one module instead of a chain.

The last one is the reason to bother. If a service test drives a real
store, then a store bug fails the service test, and the failure no longer
tells you where to look.

Two rules keep mocks honest:

- **A mock states a contract, it does not reimplement one.** If you find
  yourself writing branching logic inside a fake, you picked the wrong
  seam. Move the boundary, or write the test one layer up.
- **Mocks can lie, and the layer above is what catches it.** A fake that
  returns what you assumed keeps passing after the real collaborator
  changes. That is why the pyramid has more than one layer: the base says
  each module is right, the middle says they agree.

Using the real thing is fine where it is cheap and authoritative. An
in-memory SQLite store is both, and faking it would mean a second store
implementation to keep correct. Judge by the same question: when this
test fails, does it name one module?

## Testing behavior that relies on concurrency

Two questions come up every time: how does the test know the work is
done, and what happens if it never finishes. The rules in CONTRIBUTING
follow from the answers.

Where the work gives you a handle, use it. A thread has `join()`, an
event has `wait()`, a task can be awaited. These return the moment the
work is done, so the test runs at the speed of the machine instead of at
the speed of a number you picked.

Some work gives you no handle. A uvicorn server sets a `started` flag,
and a server in a subprocess simply begins accepting connections. Read
the condition in a loop until it is true or a timeout expires, then
assert it. `wait_until` in `tests/servers.py` is that loop, and it holds
the only `time.sleep()` in the suite:

```python
wait_until(lambda: server.started, "uvicorn did not come up")
```

The timeout turns "the server never came up" into a failure with a
message, rather than a test that hangs until CI gives up. The assert
after the loop is what makes that failure say something.

A fixed sleep gives you neither. `time.sleep(2)` followed by an assert
passes on your laptop, fails on a loaded CI runner, and when it fails it
tells you nothing about why.

## Naming

Every test is named `given_{x}_when_{y}_then_{z}`. The name is the
documentation: a CI failure line should tell you the scenario without
opening the file.

Write the name for the current state of the system. It says what is true
now, never what changed, and never mentions a feature that was removed.
`test_given_a_read_token_when_calling_an_undeclared_tool_then_it_is_403_as_unknown`
needs no follow-up reading. That is the bar.

## What to write down

Keep commentary to a minimum. The test name says what is checked, the
code says how, and a contributor's reading time belongs in `src/`.

- **Test functions get no docstring**, at any layer. The name carries it.
- **Test support code gets no docstring.** Helpers and fixtures hold no
  decision that production code depends on.
- **Integration and end to end files open with one line** saying what the
  file covers, because their filenames name a behavior and cannot.
- **Comment only what the code cannot say.** `free_port()` in
  `tests/servers.py` carries three lines about a race between picking the
  port and binding it, because nothing in three lines of socket code
  shows that, and someone will otherwise try to fix the flake in the
  wrong place.

A comment starting `Deliberate:` marks behavior that is intentional and
should not be changed casually. If you need to change it, say why in
the PR.

## Running the suite

```console
$ python -m pytest -q            # what CI runs
$ python -m pytest -q -m 'not e2e'   # skip the tests that start servers
$ python -m pytest -q -m integration # the orchestrator smoke test, opt in
```

Two markers exist, and they say what a test needs in order to run, not
which layer it belongs to:

- `e2e` drives a real client session against the built server, in memory
  or over localhost. It runs by default. A test that opens a client
  session in its own body carries it.
- `integration` exercises a real orchestrator or a live Kyno. It is
  deselected by default, so you opt in.

Postgres tests run when `KYNO_TEST_POSTGRES_URL` is set and skip
otherwise. CI holds coverage at 90%, counting only shipped behavior.

## Where the suite stands

The move is in progress. The unambiguous files now live in their target
`core`, `surface`, and `checks` lanes, and the adapter suites that mixed
scripted SDK behavior with real control-plane behavior are now split
between `surface/unit` and `core/integration`. The remaining mixed core
files are listed in `tests/layout_manifest.toml`; the MCP contract is now
split across all three lanes, and each remaining mixed file will be split
before it is moved. New tests follow the target layout now, so the tree does
not grow the old ambiguity while the remaining files are migrated.
