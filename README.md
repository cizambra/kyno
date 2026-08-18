# Kyno

A **coherence control plane** for multi-agent systems: one versioned source of
truth for your system's **mission and principles** (its *constitution*), served
over [MCP](https://modelcontextprotocol.io) so every agent can act on the
direction in force *right now* — even when that direction changes mid-flight.

## Why

When a multi-agent system's goals change, agents holding a stale copy of the
old direction keep producing work for it — and worse, quality checks against
the stale copy actively push work *back* toward the obsolete goal. Kyno
removes the stale copy: direction lives in one versioned store, agents pull the
current version at each step boundary, and subscribers are notified the moment
it changes.

## Quick start

```bash
pip install .             # from a clone; CLI: kyno
kyno init-db
kyno set --mission "Ship a lending product people trust" \
         --note "initial constitution"
kyno current
kyno serve --transport stdio    # or --transport http
```

A constitution is a **mission** (the overarching purpose — the tie-breaker when
principles conflict) plus ordered **principles**. Every change appends a new
immutable version with a plain-language change note; nothing is edited in
place, so "what was the direction when agent X acted" is always answerable.

## Writing one

A one-line principle is a handle, not a rule. Give a constitution as much as
it needs and no more — each of these is optional:

- a **declaration**, the long-form document the mission is the headline of;
- a **description** under any principle, the paragraph that settles an
  argument about what the handle means.

Both are prose, and prose through command-line flags is misery, so a
constitution is written in a file:

```yaml
# constitution.yaml
mission: Ship a lending product people trust with their worst month
declaration: |
  ## What we are for

  Lending is a promise about somebody's worst month. We would rather lose
  the deal than make a promise we cannot keep.

  ## What that costs us

  - We say no early, in plain words, rather than late in a maze.
  - We publish the number before the story that softens it.
principles:
  - Say the hard number first
  - title: Refuse quietly
    description: |
      A refusal is a sentence, not a maze. If we cannot lend, say so on the
      first screen and say why.
note: the constitution as written
by: camilo
```

```bash
kyno set --file constitution.yaml
kyno set --file constitution.yaml --constitution eu --note "the EU edit"
```

The declaration is **markdown**, and the published page renders it: headings,
lists, emphasis, quotes, links. Raw HTML inside it is escaped rather than
passed through, and `javascript:` links are refused — the page is served to
anonymous visitors, so your own text can never reach them as markup that runs.
Images are not rendered either, which is what keeps the page a single
self-contained response.

Everywhere else the declaration stays exactly the markdown you wrote: the JSON
endpoint, the MCP tools and `kyno export` all serve the source, not the
rendered document.

`--note`, `--by` and `--constitution` may override the file, because they are
about this edit rather than about the constitution; the field flags
(`--mission`, `--declaration`, `--principle`) cannot be combined with `--file`,
because two sources for one field is a question nobody should have to answer.
Fields the file leaves out are carried forward from the previous version —
clearing one is spelled `declaration: ""`.

The flags are still there for a quick edit:

```bash
kyno set --mission "Ship a lending product people trust" --note "sharpen the mission"
```

## The contract

Over MCP or Python:

- `get_constitution` — the direction in force now (mission, principles, version).
- `get_changes_since(known_version)` — the pull an agent makes before a step:
  the current direction plus the change notes since the version it last saw. A
  missed notification is harmless — the next pull is self-describing.
- `get_mission`, `get_declaration`, `get_principles`, `get_principle(title)` —
  one piece of the document each, for when a compact read left it out.
- `set_direction(mission?, declaration?, principles?, change_note)` — append the
  next version. Omitted fields carry forward; `""` clears one. On HTTP this
  requires the bearer token.

Every read is **as small as it can be by default** — handles, not the long
text — because an agent pulls before every step and would otherwise buy the
whole document each time. Ask for more when something actually needs it:
`detail="full"` on the two pulls, `detail="full"` on `get_principles`, or one
of the targeted reads. Every answer carries the version it came from, so a
client mixing them can tell when they have drifted apart.

Clients may also subscribe to the `kyno://constitution/current` resource and
receive a standard MCP `resources/updated` notification on every version bump.
It serves the compact form: a resource takes no parameters, and the whole
document is one tool call away.

## Multiple constitutions

One Kyno can hold several constitutions side by side — say one per product
line or per jurisdiction. Every operation takes an optional `constitution`
name, over MCP and on the CLI (`--constitution eu`), and defaults to
`"default"`, so a single-constitution setup never has to mention it. Each name
has its own version sequence: bumping `eu` to v2 leaves `default` at whatever
version it was. A name you have never written to reads as the same version-0
empty state an untouched store does. The subscribable resource is the default
constitution's; agents on another one pull it by name with `get_changes_since`.

## Adapters (CrewAI, LangGraph)

```bash
pip install "kyno[crewai]"      # or: pip install "kyno[langgraph]"
```

An adapter binds a crew or a graph to one **named constitution** and re-binds
every next step to the version in force right now:

```python
from kyno.adapters.core import (
    DirectionBinder,
    KynoBinding,
    McpDirectionSource,
    SessionRunner,
    http_session,
)
from kyno.adapters.crewai import CrewAiKyno

binding = KynoBinding.from_env(constitution="eu")  # KYNO_URL, KYNO_TOKEN
runner = SessionRunner(http_session(binding))
runner.start()

binder = DirectionBinder(McpDirectionSource(runner))
adapter = CrewAiKyno(binder, constitution=binding.constitution)
adapter.register()  # injects the current direction before each model call
crew = Crew(..., task_callback=adapter.task_callback)  # gates each finished task
```

Embedding Kyno in the same process instead? Swap the source:
`DirectionBinder(LocalDirectionSource(control_plane))`.

- **Pull before each step** — the current mission and principle titles are
  injected into the next model call, tagged with the constitution and version
  they came from. That block rides on every model call, so it stays small by
  default. Bind with `DirectionBinder(source, context="full")` when you would
  rather spend the tokens: the declaration and the principle descriptions are
  injected too, and the pull fetches them rather than just the handles. When
  Kyno is unreachable — or answers with something unreadable — the pull
  degrades: the step runs on the last direction the binder holds, and the
  staleness is emitted as telemetry. Bind with
  `DirectionBinder(source, policy=PullPolicy(fail_closed=True))` when your
  posture is "no direction, no work": the step raises instead of proceeding.
- **Push consumption** — `BackgroundSubscriber` turns an MCP
  `resources/updated` notification into a re-pull *by name*. A step already
  running is never interrupted; the next one binds the new direction.
- **Realignment gate** — model-free, and reviewed **per finished task**
  (CrewAI's task-completion callback), not after every LLM call — cheaper and
  less noisy once a real judge is attached, and the finished task is already
  the reviewable unit. It calls a `VerdictSource` you supply and raises
  (CrewAI, from `task_callback`) or `interrupt()`s for a decision (LangGraph)
  on `DRIFTED`. With **no judge available the work proceeds, marked
  `unchecked`**, and the event is emitted as telemetry: the default trades a
  skipped check for an uninterrupted run. Set `GatePolicy(fail_closed=True)`
  on a gate that should stop instead.
- **Adapters are read-only** — they pull and subscribe; `set_direction` stays
  an operator/CLI action against Kyno, never something an adapter calls on a
  crew's or graph's behalf.

On LangGraph, inherit `KynoState` in your graph's state schema. LangGraph
carries only the keys a schema declares, so without it the direction a node
pulls never reaches the gate node that judges against it:

```python
from kyno.adapters.langgraph import KynoState, direction_node, gate_node


class State(KynoState, total=False):
    output: str
```

## Storage

SQLite out of the box; PostgreSQL for production via `KYNO_DATABASE_URL`.
Storage is pluggable: hand `SqlConstitutionStore` your own SQLAlchemy `Engine`
to live inside an existing database, or implement the small store protocol to
bring your own persistence entirely. Concurrent writers are safe — versions are
serialized by a unique index and a retry, never lost or duplicated.

Reads never fail on an empty store: before any direction is set, consumers get
a version-0 empty state, so integrating Kyno ahead of adopting it costs
nothing.

## Publishing your constitution

If you want to show people the principles you say you operate by, Kyno can
serve that page itself — so the published page and the one your agents obey
are the same record, not two copies that drift.

```bash
kyno publish                                  # the default constitution
kyno publish --constitution eu --with-history
kyno unpublish --constitution eu
```

While `kyno serve --transport http` is running, a published constitution is
readable by anyone at:

- `GET /constitutions/{name}` — a self-contained HTML page (no scripts, no
  external assets, light and dark). The declaration is the body of it, rendered
  from markdown, and a described principle carries its paragraph.
- `GET /constitutions/{name}.json` — the same content, machine-readable.
- `GET /constitutions/` and `GET /constitutions.json` — an index of what you
  have published.

Two things worth knowing:

- **A published name has to be a slug** — lowercase letters, digits and single
  hyphens (`acme`, `acme-eu`). It is both the URL and the name your agents use,
  so Kyno refuses anything else rather than quietly rewriting it. Names you
  never publish are unrestricted.
- **Nothing is public until you publish it**, and publication is per name. One
  Kyno can hold your internal constitution and your public one side by side;
  publishing the second does nothing to the first.
- **Publishing shows the current direction only** — mission, declaration,
  principles, version, last-changed date. The version history stays private
  unless you add `--with-history`, because change notes are written for your
  operators and routinely explain *why* you changed course. A published
  history shows the 100 most recent versions — that is the page's contract;
  the full history stays available to authenticated callers over MCP and
  `kyno export`.

Anything you have not published answers `404`, exactly as a name that does not
exist does. Nothing on the public side reveals which of the two it was.

### Making it yours

For a recolor, six environment variables. Set the ones you care about and leave
the rest:

| Variable | Default | What it colors |
| --- | --- | --- |
| `KYNO_PAGE_ACCENT` | `#6d6d66` | link underlines, principle numbers |
| `KYNO_PAGE_BACKGROUND` | `#fbfbf9` | the page |
| `KYNO_PAGE_TEXT` | `#1b1b19` | body text |
| `KYNO_PAGE_MUTED` | `#6d6d66` | labels, dates, the version stamp |
| `KYNO_PAGE_RULE` | `#e4e3de` | the hairlines between items |
| `KYNO_PAGE_FONT` | system sans | `font-family` for the page |

Unset, you get the built-in look, with its automatic dark mode. Set **any color** and Kyno
stops swapping the palette for dark mode — inverting colors you chose would
give you a page you never approved, so past that point the palette is yours.
Setting only the font keeps the dark swap.

### Making it yours properly

The pages Kyno serves are template files, and it will hand you the real ones:

```bash
kyno page export ./pages          # constitution.html, index.html, page.css
```

Edit them, then point Kyno at your copies — it prints these two lines for you:

```bash
export KYNO_CONSTITUTION_TEMPLATE=/srv/pages/constitution.html
export KYNO_INDEX_TEMPLATE=/srv/pages/index.html      # optional
```

That is the whole workflow. What you exported is what Kyno was already
rendering — the same files, filled the same way — so you are editing a working
page rather than reconstructing one, and anything you leave alone keeps working.

`kyno page export` refuses to overwrite files that are already there, and
writes nothing at all when it would have to.

The exported `page.css` is a **starting point for your own styles**: link it,
inline it, or throw it away. The `$stylesheet` placeholder below always serves
the styles built into Kyno, not your copy of them — so a template keeping
`$stylesheet` stays on the house look (and follows the color variables above),
and one that drops it is fully yours.

#### Placeholders

**`constitution.html`**

| Placeholder | What it is |
| --- | --- |
| `$stylesheet` | the whole `<style>` block: color variables + Kyno's page styles |
| `$name` | the constitution's name |
| `$mission` | the mission, or the name when there is no mission |
| `$declaration` | the declaration rendered from markdown, wrapped in its `<div>` — empty when there is none |
| `$principles` | the principles section, heading and list — empty when there are none |
| `$version` | the version number, e.g. `3` |
| `$updated` | the last-changed date, e.g. `2026-08-13` |
| `$history` | the version history block — empty unless you published history |

**`index.html`**

| Placeholder | What it is |
| --- | --- |
| `$stylesheet` | as above |
| `$items` | the list of published constitutions, or the "nothing published yet" line |
| `$count` | how many are published |

Each block placeholder brings its own wrapper and disappears entirely when it
has nothing to say, so a template never has to ask "what if there is no
declaration". That is deliberate: these are **placeholders, not a template
language** — no loops, no conditions, no expressions — and the defaults are held
to the same limit, which is why they are the same files you just exported.

The safety property that buys: Kyno escapes your mission, principles and
change notes *before* they reach your file, and renders your declaration's
markdown with HTML disabled, so no template can turn text somebody typed into a
constitution into markup that runs. A placeholder you misspell is left alone
rather than breaking the page, and if your file is missing or unreadable when a
request arrives, Kyno serves its own page and logs a warning — a bad template
never takes your public page down.

## Auth

- **stdio**: open. A process that can spawn the server already owns the
  database file under it; a token there would be ceremony, not a boundary.
- **HTTP**: a shared bearer token (`KYNO_TOKEN`) gates every request to the
  MCP endpoint (`/mcp`). The server refuses to start tokenless over HTTP unless
  you explicitly opt in (`KYNO_ALLOW_INSECURE_HTTP`, local experimentation
  only — it warns), and a `KYNO_TOKEN` that is set but blank is a
  configuration error rather than silently no auth. Embedders building the app
  in code opt in the same way: `build_http_app(..., allow_insecure=True)`. The
  published constitution pages above sit outside that gate on purpose — they
  are the surface you chose to open.

The write token is **direction control**: whoever holds it steers the
instructions of every agent bound to this Kyno. Treat it like a
system-prompt credential — serve `/mcp` over TLS and keep the token out of
logs and checkpoints (Kyno's own reprs never print it). Relatedly, the
`[kyno:direction …]` header on the injected block is transcript
bookkeeping, not an authenticity boundary: text arriving from tools or users
can imitate it, so nothing should trust a block for looking like one. Kyno
refuses constitution text containing the marker, and the adapters only ever
replace the block they injected themselves.

## Deploying

- Use an **absolute `KYNO_DATABASE_URL`** in production. The default
  (`sqlite:///kyno.sqlite3`) is a dev convenience that resolves against
  whatever working directory the process starts in.
- Run a hosted Kyno **behind a reverse proxy that enforces rate limits**;
  the public pages answer anonymous traffic, and rate limiting is the
  proxy's job, not Kyno's.
- Field sizes are part of the API contract: mission ≤ 4,000 characters,
  declaration ≤ 200,000, change note ≤ 2,000, up to 100 principles with
  titles ≤ 300 and descriptions ≤ 4,000, constitution names ≤ 200.
  `set_direction` refuses anything larger, and `/mcp` request bodies are
  capped at 5 MB.
- A pip-installed Kyno carries its own migration scripts: `kyno init-db`
  creates a fresh schema stamped at the current head, and `kyno upgrade-db`
  brings an existing database up to date after an upgrade.

## Testing

```bash
python -m pytest -q                      # SQLite, no network
KYNO_TEST_POSTGRES_URL=postgresql+psycopg://… python -m pytest -q   # + Postgres
```

Sibling project: [Canon](https://github.com/cizambra/canon) tests whether your
system's outputs actually *cohere* with the constitution Kyno serves.

See [CONTRIBUTING.md](CONTRIBUTING.md) for style and test expectations.
