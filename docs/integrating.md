# Building a Kyno integration

Kyno ships adapters for CrewAI and LangGraph. If you use a different
framework or language, this page describes everything the shipped adapters
do, so you can build the same behavior on your stack.

The whole integration is this loop:

```
known = 0
last_direction = None

for each step:
    try:
        changes = kyno.get_changes_since(known)          # MCP tool call
        last_direction = build_block(changes)             # section 2
        known = changes.current_version
    except KynoUnreachable:
        pass                                              # keep last_direction
    run_step(context = last_direction + step_context)     # block goes first
```

One thing to be clear about: **your orchestrator code makes this call, not
the model.** The agent never sees a Kyno tool it can choose to use — the
adapter pulls before each step and places the finished block in the
context. Direction is delivered, not offered.

Three rules hold it together: ask before every step, put the answer first,
and never let a failed ask break the step. The sections below give the
details for each part.

## 1. The call

Call the `get_changes_since` MCP tool with the last version you saw (`0` if
you've never asked):

```json
{ "known_version": 0, "constitution": "default", "detail": "compact" }
```

Response:

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

- If no direction has been set yet, you get version `0` and empty fields.
  That is a valid state, not an error.
- `detail: "compact"` returns the mission and principle titles;  `"full"`
  adds the declaration and each principle's description. Use compact unless
  you need the rest — this call runs on every step.
- Always include `delta` in your block when it's present. It lists what
  changed, in plain sentences, and it is the single highest-impact part of
  the payload.

## 2. The block

Format the response as text and put it at the **front** of the step's
context — before the agent's identity, before the task:

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

- The first line is always the marker. It records which constitution and
  version this step ran under, so any transcript can be audited later.
- Version `0`: the block is the marker plus one line —
  `No direction has been set yet.`
- `"full"` detail: add `Declaration:` and its text after the mission, and
  indent each principle's description under its title.
- Skip `Recent changes:` and `What changed:` when they're empty.
- Send the block on **every** step, even when nothing changed. A
  constitution sent only once scrolls out of the context window as the
  session grows.

## 3. When Kyno is unreachable

Never fail the step because the pull failed:

- Have a previous response? Reuse it. Its marker still shows the version it
  came from, so the transcript stays accurate.
- Never reached Kyno at all? Use the version-`0` block.
- Log the failure either way.

If your use case must halt when the direction is unknowable (a compliance
process, for example), failing the step is a valid choice — make it an
explicit setting, not the default.

## 4. Pushes are optional

Kyno sends `notifications/resources/updated` on the resource
`kyno://constitution/current` when a new version is appended. If your MCP
client supports subscriptions, use them to pull sooner. They are an
optimization only: an integration that just pulls works correctly; one that
only listens does not. Never build the block from a push payload.

## 5. If your orchestrator plans first

Pull at planning time too, and plan against the block. If a later pull
returns a higher version than the plan was made under, re-plan the
remaining work against the new block. Completed steps stay as they are.

## You're done when

- [ ] Every model call's context starts with the block, carrying the newest
      version Kyno had at that moment.
- [ ] A `set_direction` while your system is mid-run appears in the very
      next step's marker.
- [ ] Killing Kyno mid-run changes nothing except a log line — steps
      continue on the last-known block.
- [ ] For any past step, the marker alone tells you which constitution and
      version it ran under.
- [ ] `delta` lines appear in the block whenever the server sends them.

## How the shipped adapters implement this page

| this page | in the code |
|---|---|
| the loop (pull, build, failure rules) | `DirectionBinder.bind()` — `src/kyno/adapters/core/binder.py` |
| the call, over MCP | `McpDirectionSource` — `src/kyno/adapters/core/client.py` (or `LocalDirectionSource` when Kyno runs in-process) |
| the block | `Direction.render()` — `src/kyno/adapters/core/cell.py` |
| failure rules | `PullPolicy` — `src/kyno/adapters/core/policy.py` |
| pushes | `BackgroundSubscriber` — `src/kyno/adapters/core/subscriber.py` |
| putting the block first | `CrewAiKyno.before_llm_call` — `src/kyno/adapters/crewai/hooks.py`; `direction_node` / `pull_before` — `src/kyno/adapters/langgraph/nodes.py` |

If you build one of these for a framework others use, we'd welcome a PR.
