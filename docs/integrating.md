# Building a Kyno adapter in any language

An adapter is the piece of code that connects your orchestrator to Kyno.
Its job is small: before each agent step, fetch the current direction from
Kyno and place it at the front of the step's context. This guide builds
that up in five stages. Every stage ends with a check, so you always know
whether what you have so far is correct before you move on.

One thing to be clear about before you start: **the point of an adapter is
to make sure the call to Kyno happens on every step.** Kyno serves MCP,
so you could simply add it to your agents' tool list and let the model
call `get_changes_since` itself, but then the call is optional, and
the model decides when the direction matters. In our benchmark, setups
where the direction was optional scored at the bottom of every table. The
adapter removes that decision: your orchestrator code fetches before each
step and puts the finished text in the context, so the agent never chooses
whether to consult the direction: it always has it. (If you're in Python
you don't need to build any of this: `pip install kyno`, and
`DirectionBinder` already does it all. This guide is for every other
language.)

The [repo](https://github.com/cizambra/kyno) ships everything you need to
test against, in the `conformance/` folder: a sample constitution, and
example files showing exactly what Kyno returns and exactly what your
adapter should produce. `pip install` gives you the server; the
`conformance/` files come from the repo, so clone it or download that
folder.

On this page:

- [Stage 1: call Kyno and get the direction](#stage-1-call-kyno-and-get-the-direction)
- [Stage 2: turn the response into the block](#stage-2-turn-the-response-into-the-block)
- [Stage 3: wire it into your orchestrator](#stage-3-wire-it-into-your-orchestrator)
- [Stage 4: a change arrives mid-run](#stage-4-a-change-arrives-mid-run)
- [Stage 5: Kyno goes down](#stage-5-kyno-goes-down)
- [Done](#done)


## Stage 1: call Kyno and get the direction

Start a local Kyno with the sample constitution:

```bash
pip install kyno
kyno init-db
kyno set --file conformance/v1.yaml
KYNO_TOKEN=test-token kyno serve --transport http
```

Kyno speaks [MCP](https://modelcontextprotocol.io), a standard protocol
with client libraries in most languages. From your language, call the tool
`get_changes_since` with these arguments:

```json
{ "known_version": 0, "constitution": "default", "detail": "compact" }
```

`known_version` is the last version number you saw; `0` means "I haven't
seen any yet".

Here is that call in three languages. Every example on this page was run
against a Kyno started exactly as above before being committed.

**Python** (`pip install mcp`):

```python
import asyncio, json
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def main():
    headers = {"Authorization": "Bearer test-token"}
    async with streamablehttp_client("http://localhost:8080/mcp/", headers=headers) as (
        read,
        write,
        _,
    ):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "get_changes_since",
                {"known_version": 0, "constitution": "default", "detail": "compact"},
            )
            response = json.loads(result.content[0].text)
            print(response["current_version"], response["mission"])


asyncio.run(main())
```

**TypeScript** (`npm install @modelcontextprotocol/sdk`):

```typescript
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";

const transport = new StreamableHTTPClientTransport(
  new URL("http://localhost:8080/mcp/"),
  { requestInit: { headers: { Authorization: "Bearer test-token" } } },
);
const client = new Client({ name: "my-adapter", version: "0.1" });
await client.connect(transport);

const result = await client.callTool({
  name: "get_changes_since",
  arguments: { known_version: 0, constitution: "default", detail: "compact" },
});
const response = JSON.parse(result.content[0].text);
console.log(response.current_version, response.mission);
await client.close();
```

**Ruby, or any language without an MCP client library**: the protocol is
three plain HTTP POSTs to the same URL: one to open a session, one to say
you're ready, one to call the tool. The session id comes back in the
`mcp-session-id` response header, and replies arrive as a server-sent
event, so the JSON is on the line that starts with `data: `:

```ruby
require "net/http"
require "json"
require "uri"

URL = URI("http://localhost:8080/mcp/")
HEADERS = {
  "Authorization" => "Bearer test-token",
  "Content-Type" => "application/json",
  "Accept" => "application/json, text/event-stream",
}

def post(body, session_id: nil)
  headers = HEADERS.dup
  headers["Mcp-Session-Id"] = session_id if session_id
  Net::HTTP.post(URL, JSON.dump(body), headers)
end

init = post({ jsonrpc: "2.0", id: 1, method: "initialize",
              params: { protocolVersion: "2025-06-18", capabilities: {},
                        clientInfo: { name: "my-adapter", version: "0.1" } } })
session_id = init["mcp-session-id"]
post({ jsonrpc: "2.0", method: "notifications/initialized" }, session_id: session_id)

reply = post({ jsonrpc: "2.0", id: 2, method: "tools/call",
               params: { name: "get_changes_since",
                         arguments: { known_version: 0, constitution: "default",
                                      detail: "compact" } } }, session_id: session_id)
data = reply.body.lines.find { |l| l.start_with?("data: ") }.delete_prefix("data: ")
response = JSON.parse(JSON.parse(data).dig("result", "content", 0, "text"))
puts "#{response["current_version"]} #{response["mission"]}"
```

**Check:** the response must equal the file
`conformance/expected/response_version1_compact.json`, word for word. If it
does, stage 1 is done.

Two details you'll need later:

- If you call before any direction has been set, you get
  `current_version: 0` and empty fields. That is a normal response, not an
  error, and your code should handle it like any other.
- `detail: "compact"` returns the mission and the principle titles.
  `detail: "full"` also returns the declaration and each principle's
  description. Use compact unless you need the rest; this call runs before
  every step.

## Stage 2: turn the response into the block

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
  section when its list is empty. The `delta` lines matter most: they tell
  the agents what changed since the last version.
- With `detail: "full"`, add `Declaration:` and its text after the mission
  line, and put each principle's description on an indented line under its
  title.

The whole function, in TypeScript. A direct translation works in any
language:

```typescript
export function buildBlock(response, constitution = "default", detail = "compact") {
  const marker = `[kyno:direction constitution=${constitution} version=${response.current_version}]`;
  if (response.current_version === 0) {
    return `${marker}\nNo direction has been set yet.`;
  }
  const lines = [marker, `Mission: ${response.mission}`];
  if (detail === "full" && response.declaration) {
    lines.push("Declaration:", response.declaration);
  }
  if (response.principles.length > 0) {
    lines.push("Principles:");
    for (const p of response.principles) {
      lines.push(`- ${p.title}`);
      if (detail === "full" && p.description) lines.push(`  ${p.description}`);
    }
  }
  if (response.change_notes.length > 0) {
    lines.push("Recent changes:", ...response.change_notes.map((n) => `- ${n}`));
  }
  if (response.delta.length > 0) {
    lines.push("What changed:", ...response.delta.map((d) => `- ${d}`));
  }
  return lines.join("\n");
}
```

**Check:** run your function on the example responses and compare with the
example blocks, character for character:

| your input | must produce |
|---|---|
| `response_before_any_direction.json` | `block_before_any_direction.txt` |
| `response_version1_compact.json` | `block_version1_compact.txt` |
| `response_version1_full.json` (from `detail: "full"`) | `block_version1_full.txt` |
| `response_version2_after_knowing_1.json` | `block_version2_compact.txt` |

All four match, and stage 2 is done.

## Stage 3: wire it into your orchestrator

Before this stage, everything you have built is identical for every
adapter, in every framework: the call and the block do not care what
orchestrator they serve. This stage is the only framework-specific part,
and it comes down to two things: where your framework's before-each-step
hook lives, and what "the front of the context" means there (a messages
list in some frameworks, a state object in others). If an adapter already
exists in your language for a different framework, reuse its code for
stages 1 and 2 as-is and rewrite only this stage.

Now put the two pieces together. Find the place in your orchestrator that
runs right before each agent step (most frameworks have a hook, callback,
or middleware for this). In that place:

1. Call `get_changes_since` with the last version you saw.
2. Build the block.
3. Put the block at the very front of the step's context, before the
   agent's role or system prompt, before the task.
4. Remember the version number for the next call.

Do this on every step, even when nothing changed. A direction that is only
sent once falls out of the context window as the conversation grows.

In TypeScript, the whole thing, including the stage-5 rule that a failed
fetch reuses the last block instead of crashing the step:

```typescript
let knownVersion = 0;
let lastBlock = "[kyno:direction constitution=default version=0]\nNo direction has been set yet.";

async function fetchBlock() {
  try {
    const response = await callGetChangesSince(knownVersion);  // the call from stage 1
    knownVersion = response.current_version;
    lastBlock = buildBlock(response);                          // the function from stage 2
  } catch {
    console.error("kyno unreachable, reusing the last block");
  }
  return lastBlock;
}

// this part goes in your orchestrator's before-each-step hook:
const block = await fetchBlock();
const context = block + "\n\n" + stepContext;
appendFileSync("my_blocks.log", block + "\n---end---\n");   // the log the checker reads
```

**Check:** while your orchestrator runs, append every block you inject to a
log file, each followed by a line containing only `---end---`. Then run the
checker that ships with Kyno:

```bash
python -m kyno.conformance check my_blocks.log
```

It verifies every block starts with the marker, empty-state blocks are
exact, and the version number never goes backwards. `all checks passed`
means stage 3 is done.

## Stage 4: a change arrives mid-run

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

The change must appear on the step right after you published it, not
several steps later, and not never. The blocks from that step on must also
contain the `What changed:` lines (compare with
`block_version2_compact.txt`).

## Stage 5: Kyno goes down

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
  a notification is a good moment to fetch sooner. It's optional, because fetching
  before every step already keeps you correct.
- **Planning.** If your orchestrator makes a plan before executing it,
  fetch the direction at planning time too, and re-plan the remaining steps
  whenever a fetch returns a higher version than the plan was made under.

If your adapter targets a framework other people use, we'd welcome a PR.
The Python versions of everything on this page live in the SDK,
`src/kyno/sdk/`: the fetch-and-build loop is `DirectionBinder.bind()`
(`binder.py`), the block builder is `Direction.render()` (`cell.py`), and
the block rule is `refresh()` (`cell.py`). The framework adapters in
`src/kyno/adapters/` show where each framework's before-each-step hook
lives: `CrewAiKyno.before_llm_call` (`crewai/hooks.py`) and
`direction_node` (`langgraph/nodes.py`). If your orchestrator plans first,
`binder.plan()` (`sdk/plan.py`) is the tracker described in stage 5.
