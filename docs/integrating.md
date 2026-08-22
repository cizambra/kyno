# Building a Kyno integration

Kyno ships adapters for CrewAI and LangGraph. If your stack is something
else — another framework, another language — this page covers everything the
shipped adapters do. Follow it and your agents get the same steering: every
step acts on the direction in force *right now*, and a change reaches every
agent on its next step.

The short version: **before each step, ask Kyno what changed, put the answer
at the front of the step's context, and never let a failed ask kill the
step.** Everything below is the detail of those three moves.

## 1. Ask what changed

Kyno speaks [MCP](https://modelcontextprotocol.io). Before every step, call
the `get_changes_since` tool with the last version you saw (`0` if you've
never asked):

```json
{ "known_version": 0, "constitution": "default", "detail": "compact" }
```

You get back the current version and the direction itself:

```json
{
  "current_version": 9,
  "changed": true,
  "mission": "…",
  "principles": [ { "title": "…" }, … ],
  "change_notes": [ "…" ],
  "delta": [ "…" ]
}
```

Three things to know:

- **Reads never fail.** If no direction has been set yet, you get version
  `0` and empty fields — that's an answer, not an error.
- **`detail` is how much you want to carry.** `"compact"` returns the
  mission and principle titles; `"full"` adds the declaration and each
  principle's description. Compact is the default for a reason: agents
  consult direction constantly, and a consult should cost what it answers.
- **`delta` matters most.** When the direction changed,
  it lists what moved, in plain sentences. Don't drop it: in our benchmark,
  telling agents *what* changed (not just the new text) was the difference
  between 75% and 93% of post-change work serving the new direction.

## 2. Build the block

Turn the answer into a text block and put it at the **front** of the step's
context — before the agent's identity, before the task. The exact shape:

```
[kyno:direction constitution=default version=9]
Mission: <mission>
Principles:
- <title>
- <title>
Recent changes:
- <note>
What changed:
- <delta line>
```

Rules, in order:

- The first line is always the marker:
  `[kyno:direction constitution=<name> version=<N>]`. It's how a transcript
  answers "which direction was this agent on" with no other context.
- If the version is `0`, the block is the marker plus one line:
  `No direction has been set yet.`
- With `"full"` detail, add `Declaration:` and its text after the mission,
  and indent each principle's description under its title.
- Skip `Recent changes:` and `What changed:` when they're empty.

Send the block on **every** step, even when nothing changed. A constitution
that's only in the opening prompt scrolls out of the context window as the
session grows — in our long-run test it was in front of the model on 2 of 30
turns, and by the session's final third the agents scored the same as having
no constitution at all.

## 3. When Kyno is unreachable

A failed pull must cost freshness, never the step. Three rules:

- If you've seen a direction before, reuse the **last one you got** — its
  marker still names the version it was, so the record stays honest.
- If you've never reached Kyno, use the version-`0` block.
- Log it. An integration that silently serves stale direction for a week is
  the exact problem Kyno exists to remove.

(If your use case truly must halt when direction is unknowable — a
compliance desk, say — failing the step is a legitimate opt-in. Just make it
a choice someone made, not a default someone forgot.)

## 4. Treat pushes as hints

Kyno's MCP server exposes one resource, `kyno://constitution/current`, and
sends `notifications/resources/updated` when a new version is appended. If
your MCP client supports subscriptions, use them — but only as a nudge to
pull sooner. The pull is what you act on. Never inject direction from a
push payload, and never rely on pushes arriving: an integration that only
pulls is correct; an integration that only listens is not.

## 5. Pull when you plan, too

If your orchestrator plans before it executes, pull at planning time and
plan against the block. And when a mid-run pull comes back with a **higher
version than the plan was made under**, re-plan the remaining work against
the new block instead of finishing the old plan politely. Steps already
done are done; what's left should serve the direction now in force.

## You're done when

- [ ] Every model call's context starts with the direction block, and the
      block's version is the newest Kyno had at that moment.
- [ ] A `set_direction` while your system is mid-run shows up in the very
      next step's marker.
- [ ] Killing Kyno mid-run changes nothing except a log line — steps
      continue on the last-known block.
- [ ] Your transcript can answer, for any past step, which constitution and
      version it served — from the marker alone.
- [ ] The `delta` lines appear in the block whenever the server sends them.

If you build one of these for a framework others use, we'd love a PR — the
CrewAI and LangGraph adapters in `src/kyno/adapters/` are small and show the
same contract implemented in Python.
