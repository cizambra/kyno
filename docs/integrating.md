# Building a Kyno adapter in any language

An adapter is the piece of code that connects your orchestrator to Kyno.
Its job is small: before each agent step, fetch the current direction from
Kyno and place it at the front of the step's context. This guide builds
that up in five stages. Every stage ends with a check, so you always know
whether what you have so far is correct before you move on.

One thing to be clear about before you start: **your orchestrator code
fetches the direction, not the model.** The agent never sees a Kyno tool it
can decide to call — your adapter fetches before each step and puts the
finished text in the context. (If you're in Python you don't need to build
any of this: `pip install kyno`, and `DirectionBinder` already does it all.
This guide is for every other language.)

The repo ships everything you need to test against, in the `conformance/`
folder: a sample constitution, and example files showing exactly what Kyno
returns and exactly what your adapter should produce.

## Stage 1 — call Kyno and get the direction

Start a local Kyno with the sample constitution:

```bash
pip install kyno
kyno init-db
kyno set --file conformance/v1.yaml
kyno serve --transport http --token test-token
```

Kyno speaks [MCP](https://modelcontextprotocol.io), a standard protocol
with client libraries in most languages. From your language, call the tool
`get_changes_since` with these arguments:

```json
{ "known_version": 0, "constitution": "default", "detail": "compact" }
```

`known_version` is the last version number you saw; `0` means "I haven't
seen any yet".

**Check:** the response must equal the file
`conformance/expected/response_version1_compact.json`, word for word. If it
does, stage 1 is done.

Two details you'll need later:

- If you call before any direction has been set, you get
  `current_version: 0` and empty fields. That is a normal response, not an
  error — your code should handle it like any other.
- `detail: "compact"` returns the mission and the principle titles.
  `detail: "full"` also returns the declaration and each principle's
  description. Use compact unless you need the rest; this call runs before
  every step.

## Stage 2 — turn the response into the block

The "block" is the text your adapter puts in front of each step. Write a
function that takes the response from stage 1 and produces this:

```
[kyno:direction constitution=default version=1]
Mission: Ship a lending product people trust
Principles:
- Approve in minutes, not days
- Explain every rejection
- Never lend what someone cannot repay
Recent changes:
- initial constitution
```

The rules:

- The first line is always
  `[kyno:direction constitution=<name> version=<number>]`. This line is how
  anyone reading a transcript later can tell which version of the direction
  the step ran under.
- If `current_version` is `0`, the block is the marker line plus exactly
  one more line: `No direction has been set yet.`
- If the response has `change_notes`, add a `Recent changes:` section with
  one `- ` line each. Same for `delta` under `What changed:`. Skip either
  section when its list is empty. The `delta` lines matter most — they tell
  the agents what changed since the last version.
- With `detail: "full"`, add `Declaration:` and its text after the mission
  line, and put each principle's description on an indented line under its
  title.

**Check:** run your function on the example responses and compare with the
example blocks, character for character:

| your input | must produce |
|---|---|
| `response_before_any_direction.json` | `block_before_any_direction.txt` |
| `response_version1_compact.json` | `block_version1_compact.txt` |
| the same, with `detail: "full"` | `block_version1_full.txt` |
| `response_version2_after_knowing_1.json` | `block_version2_compact.txt` |

All four match — stage 2 is done.

## Stage 3 — wire it into your orchestrator

Now put the two pieces together. Find the place in your orchestrator that
runs right before each agent step (most frameworks have a hook, callback,
or middleware for this). In that place:

1. Call `get_changes_since` with the last version you saw.
2. Build the block.
3. Put the block at the very front of the step's context — before the
   agent's role or system prompt, before the task.
4. Remember the version number for the next call.

Do this on every step, even when nothing changed. A direction that is only
sent once falls out of the context window as the conversation grows.

**Check:** while your orchestrator runs, append every block you inject to a
log file, each followed by a line containing only `---end---`. Then run the
checker that ships with Kyno:

```bash
python -m kyno.conformance check my_blocks.log
```

It verifies every block starts with the marker, empty-state blocks are
exact, and the version number never goes backwards. `all checks passed` —
stage 3 is done.

## Stage 4 — a change arrives mid-run

Start a run that takes several steps. While it's running, publish the
second version of the sample constitution from another terminal:

```bash
kyno set --file conformance/v2.yaml
```

**Check:** run the checker on your log again. It prints where the version
changed, like this:

```
versions, step by step: [1, 1, 1, 2, 2]
  version changed at step 4: 1 -> 2
```

The change must appear on the step right after you published it — not
several steps later, and not never. The blocks from that step on must also
contain the `What changed:` lines (compare with
`block_version2_compact.txt`).

## Stage 5 — Kyno goes down

Start another multi-step run. While it's running, stop the Kyno server.

The rule: a failed fetch must never crash the step. Reuse the last block
you got (its version number stays whatever it was), write a warning to
your own log, and carry on. If you never reached Kyno at all, use the
version-0 block.

**Check:** the run finishes normally, the checker still passes on your log,
and the versions simply stop changing at the point where the server died.

## Done

If all five stages pass their checks, your adapter behaves exactly like the
ones that ship with Kyno. Two smaller things worth adding after:

- **Push notifications.** Kyno announces new versions on the MCP resource
  `kyno://constitution/current`. If your MCP client supports subscriptions,
  a notification is a good moment to fetch sooner. It's optional — fetching
  before every step already keeps you correct.
- **Planning.** If your orchestrator makes a plan before executing it,
  fetch the direction at planning time too, and re-plan the remaining steps
  whenever a fetch returns a higher version than the plan was made under.

If your adapter targets a framework other people use, we'd welcome a PR.
The Python versions of everything on this page live in
`src/kyno/adapters/`: the fetch-and-build loop is `DirectionBinder.bind()`
(`core/binder.py`), the block builder is `Direction.render()`
(`core/cell.py`), and the injection points are `CrewAiKyno.before_llm_call`
(`crewai/hooks.py`) and `direction_node` (`langgraph/nodes.py`).
