# Operating Kyno

Storage, auth, deployment, and testing for a production Kyno.

On this page:

- [The workspace](#the-workspace)
- [Storage](#storage)
- [Running Kyno embedded](#running-kyno-embedded)
- [Auth](#auth)
- [Who should hold write access](#who-should-hold-write-access)
- [Deploying](#deploying)
- [Testing](#testing)


## The workspace

A workspace is a directory that defines one Kyno instance. `kyno new`
creates it; the argument is the name of the directory to create, so pick
any name you like. Every command that needs the store finds the
workspace by walking up from the current directory, the way git does.

```console
$ kyno new my-instance
$ cd my-instance && kyno db init
$ kyno serve --transport http
$ kyno token add agents --scope read     # in another terminal
```

The endpoint checks a bearer token on every request: until one
exists, every request is refused, and a token minted while the server
runs works on the next request. Details in [Auth](#auth).

`kyno new` writes four files:

```
my-instance/
  README.md          what this directory is
  .gitignore         keeps the SQLite store out of git
  config/server      the instance's configuration
  db/.keep           where the SQLite store will live
```

Two directories, two owners:

- `~/.kyno` holds what belongs to a person: credentials and remotes. It
  never ships with a deploy.
- The workspace holds what belongs to the instance: the `config/server`
  file and, on SQLite, the store under `db/`.

The rules for the `config/server` file:

- A value is written in, or is one `${VAR}` reference to an environment
  variable you named. References resolve at startup; an unset variable
  fails startup and the error names the variable.
- Kyno never requires a reference: a password written in works. When to
  keep secrets as references is a practice call — see
  [Best practices](best-practices.md#secrets-stay-references).
- An unknown key or section fails startup and names the typo.

The `[delivery]` section accepts `recording_policy = never` (the default) or
`recording_policy = always`, including a `${VAR}` reference to either value:

```ini
[delivery]
recording_policy = never
recording_timeout_seconds = 1
```

Omitting the section or its policy defaults to `never`. Unknown keys and
other policy values fail configuration loading. Core reads the policy through
`settings.delivery.recording_policy`. See
[Recording direction served over MCP](#recording-direction-served-over-mcp)
for the recording boundary and response status.

`recording_timeout_seconds` defaults to `1` second. It accepts a positive,
finite number, including fractional seconds, or a `${VAR}` reference. Invalid
values fail configuration loading even under `never`. The setting is available
as `settings.delivery.recording_timeout_seconds` and is used by the runtime
recorder. It configures recording database wait limits, not a total
response-time deadline, and has no effect when recording is disabled.

The `[database]` section describes the database with split keys, like
Rails' `database.yml`. In this example everything is written in except
the password, which comes from a variable:

```ini
[database]
adapter = postgresql
host = db.internal
database = kyno
username = kyno
password = ${DB_PASSWORD}
```

- The default, as `kyno new` writes it: `adapter = sqlite3` with the
  store at `db/kyno.sqlite3`. SQLite can run production on a single
  box.
- A platform that hands you one connection string uses
  `url = ${DATABASE_URL}` instead. `url` beside the split keys is
  refused.

## Storage

SQLite, PostgreSQL and MySQL, declared in the workspace's `[database]`
section. Which engine runs where is the operator's call: SQLite is enough for
production on a single box, and Postgres or MySQL are equally fine for
local development. If you want postgres or mysql, you need to install
the adapter first:

```console
$ pip install kyno[postgres]
$ pip install kyno[mysql]     # MariaDB uses this one too
```
Storage is pluggable: hand `SqlConstitutionStore` your own SQLAlchemy
`Engine` to live inside an existing database, or implement the small store
protocol to bring your own persistence entirely. Concurrent writers are safe:
versions are serialized by a unique index and a retry, never lost or
duplicated.

Reads never fail on an empty store. Before any direction is set, consumers
get a version-0 empty state, so integrating Kyno ahead of adopting it costs
nothing.

## Recording direction served over MCP

Recording is off by default. To enable it, set `recording_policy = always`
under `[delivery]` in `config/server`, run `kyno db upgrade`,
and restart the server. The choices are `always` and `never`; requests cannot
override the server setting.

`always` attempts to save each successful runtime direction response, including
repeated reads of the same version. `never` stops new recording without deleting
existing records or disabling operational and security logging. Earlier
unrecorded requests cannot be reconstructed.

The covered operations are `get_constitution`, `get_changes_since`, `get_mission`,
`get_declaration`, `get_principles`, `get_principle`, and the current-constitution
MCP resource. Exports, public pages, and direct embedded reads do not record
runtime deliveries.

Runtime tool calls accept an optional `correlation_id` and JSON `metadata` object.
The application chooses which requests share a correlation ID. Correlation labels are limited
to 255 characters and metadata to 16,384 bytes under Python's default JSON
encoding. Metadata should hold non-secret correlation data, not credentials,
prompts, or outputs. Authenticated requester identity comes from the token and
is stored separately from these caller-supplied fields. Resource reads have no
caller-supplied correlation label or metadata.

The response includes a separate `recording` object:

| Status | Record ID | Meaning |
| --- | --- | --- |
| `recorded` | Present | Core confirmed that the delivery event was saved. |
| `disabled` | `null` | Recording is off; no write was attempted. |
| `failed` | `null` | Direction was returned, but persistence was not confirmed. |

The event references the immutable constitution ID and served version rather
than copying mission, declaration, principles, or change notes. It keeps the
request's last-seen version, detail level, and selection, plus the generated delta
as returned. A missing delta is null; a returned empty delta is an empty array.
Version-zero reads retain the requested name without creating a constitution.
Retrieve the referenced historical version, not current direction, when
reviewing earlier work. This is not a byte-for-byte response archive. `disabled` and `failed` create no
placeholder records. Failures produce an operational warning with the error
class, excluding direction contents and database error messages.

A server record does not confirm prompt injection, model obedience, or client
receipt after a network interruption. Cache-only work creates no server record.
There is no automatic expiration or pruning. Recording is synchronous, with
database wait limits configured by `[delivery].recording_timeout_seconds`:

- SQLite limits waits for database locks.
- PostgreSQL limits statements (including lock waits) and connection attempts,
  and configures TCP failure detection where the operating system supports it.
- MySQL limits socket reads/writes, connection attempts, and database lock waits.

Driver precision and minimums apply: SQLite/PostgreSQL statement limits round
up to milliseconds; PostgreSQL connections allow at least two seconds; MySQL
connection and lock limits round up to whole seconds. Very large settings are
capped at native limits. Separate operations can each wait, so this is not an
exact total response-time deadline or protection against every OS/network stall.

File/server databases use a separate, short-lived connection built from the
workspace database URL. Recording does not wait for the direction connection pool or
change its timeout settings. This adds connection overhead when recording is
enabled. In-memory SQLite reuses its existing connection to retain the database.
Programmatic Core integrations using file/server databases must supply an
explicit `recording_url` when constructing `SqlDeliveryRecordStore`. It must
match the direction engine URL. Custom creators, connection arguments, and
hooks are not copied; the supplied URL must carry the intended connection
configuration. Without an explicit URL, recording fails rather than guessing
where an injected engine actually connects. Workspace-based setup supplies
the URL automatically.

A timeout returns the direction with `recording.status = "failed"` and no
record ID. This means saving was not confirmed, not proof that no row exists:
for example, a connection can fail while the database is confirming a commit.
Kyno does not retry the write or keep a background recording worker running.

## Retrieving a recorded delivery

Call the authenticated MCP tool `get_delivery_record` with the `record_id` returned
in a successful recording result. Read and write tokens can both retrieve
records; an unknown ID returns an error.

The result includes the constitution ID, served version, operation, requested
constitution name, UTC recording time, requester, correlation label, metadata,
request selection, and saved delta. Direction content is not duplicated here.
Retrieve the referenced version from constitution history to review the mission
and principles that were in force, even after later updates or a restart.
Respect the recorded selection: a mission-only read does not mean the whole
constitution was served. The saved delta preserves the generated comparison
returned for that request. The internal storage sequence is not included.

Lookup remains available when `[delivery]` has `recording_policy = never`. Looking up history
does not create another delivery, including when recording is `always`.
Database failures return an availability error without database details.

## Browsing delivery history

Call `list_delivery_records` to browse delivery summaries. Each summary includes
the recorded version reference, timestamp, request context, requester,
correlation ID, and application metadata. It includes neither direction content
nor the saved delta. Use `get_delivery_record` for the delta of an individual
delivery, then retrieve its historical constitution version if needed.

Pages default to 50 records. Set `limit` to request between 1 and 100 records
per page.

Optional `correlation_id`, `constitution_key`, `since`, and `until` filters select
matching events before the page limit is applied. Time bounds are inclusive.
For the next page, pass `next_cursor` as `after` with the same filters; a null
cursor means the current results are exhausted. Events are ordered by insertion,
and new events can appear between pages. Read and write tokens may browse history.
Listing never creates another delivery record.

Both summaries and individual records expose the string `constitution_key` and
the numeric `constitution_id`. The numeric ID is null when no stored version was
served. Existing delivery records remain readable without a database migration.
Omitting the key filter or passing null includes every constitution; a blank key
is invalid.

## Running Kyno embedded

When your orchestrator is itself a Python app, you can run the control
plane inside it instead of behind `kyno serve`. The construction mirrors
what the CLI does: read the settings, build the store, and hand the
control plane to the binder.

```python
from kyno.server_config import Settings, store_from_settings
from kyno.service import ControlPlane
from kyno.sdk import DirectionBinder, LocalDirectionSource

store = store_from_settings(Settings.load())  # finds the workspace at or above cwd
control_plane = ControlPlane(store)
binder = DirectionBinder(LocalDirectionSource(control_plane))
```

Each control-plane operation selects its own constitution. Omit the name or
pass `None` to use `default`; pass `constitution_key="eu"` to select `eu` for
that operation. Selecting a name never changes subsequent operations.

Core resolves an omitted selection to `default`. Adapters, the SDK, and MCP
preserve omission until Core answers. Direct SQL store operations require an
explicit key.

Constitution keys are unique within a database. Surrounding whitespace is
trimmed; the remaining 1–200 characters must be lowercase ASCII letters or
digits separated by single hyphens, such as `eu-west`. Blank keys are invalid.
For delivery-history filters, an omitted key or `None` selects all constitutions.

Embedded direction and publication results expose `constitution_key`, including
empty direction reads. This is the resolved key, so callers can identify what
Core selected even when the request omitted it.

The schema has to exist before the first read, so run `kyno db init` once
against the same database, or call `store.create_all()` from code. From
here the binder behaves exactly as it does over MCP, and the CLI keeps
working against the same database for edits and inspection.

## Auth

- **stdio** is open. A process that can spawn the server already owns the
  database file under it, so a token there would add a step without adding
  protection.
- **HTTP** is gated by the token inventory. Every request to the MCP
  endpoint (`/mcp`) must carry a live minted token as its bearer; the
  server hashes what arrived and looks it up. Unknown, revoked and expired
  all get the same 401, so a caller cannot use the response to find out
  which tokens exist. A `read` token can call every tool except
  `apply_direction`; `apply_direction` needs `write` and answers 403
  otherwise. Every tool declares the scope it needs, and a tool the
  server does not declare is refused for every token: a new tool is
  unreachable until someone states what it requires. A server with no live tokens still
  starts: it refuses every /mcp request until one is minted, and a note
  on stderr at startup says that is what will happen and names the
  command that mints one. You can start the server first and mint
  tokens later. The endpoint checks the database on every request, so a
  token minted while the server runs works on the next request, with no
  restart. To turn the check off entirely, set `allow_insecure = true`
  in `config/server`. That opens the endpoint to anyone who can reach
  it, so it is for local experimentation only, and the server prints a
  warning at startup saying exactly that: it is serving without token
  checks, and the constitution can be rewritten by anyone who can reach
  the endpoint. Embedders building the app in
  code pass their store — `build_http_app(cp, token_store=store)` — or opt in
  the same way:
  `build_http_app(cp, allow_insecure=True)`. The published constitution
  pages above sit outside that gate on purpose; they are the surface you
  chose to open.

A write token is direction control: whoever holds it steers the
direction available to agents consuming the constitutions they change. Treat it like a system-prompt
credential: serve `/mcp` over TLS and keep the token out of logs and
checkpoints (Kyno's own reprs never print it). One related caution: the
`[kyno:direction …]` header on the injected block is a record for reading
transcripts, not a security check. Text arriving from tools or users can
imitate it, so nothing should trust a block just for looking like one. Kyno
refuses constitution text containing the marker, and the adapters only ever
replace the block they injected themselves.

### Who should hold write access

Give agent applications **read-only tokens**. Keep write tokens in a
separate operator environment or trusted deployment job. An agent needs
to receive direction, not permission to rewrite it.

The distinction is about credentials and process access, not just which
tools you show the model. Shipped adapters only pull, but an application
holding a write token can call `apply_direction` directly. Removing that
tool from the agent's tool list does not reduce the token's authority.

```mermaid
flowchart LR
  O["Operator or trusted deployment job<br/>write token"] -->|"apply reviewed direction"| K["Kyno HTTP endpoint"]
  A["Agent application<br/>read token only"] -->|"pull direction"| K
  K -->|"versioned direction"| A
```

These are separate credential environments. Do not give the agent process
access to the operator's write token, credentials file, or database
credentials. Do not put write credentials in prompts, tool results, logs,
saved workflow state, or direction receipts. A variable reference avoids
copying the secret into configuration; it does not protect the secret
from a process that can read the referenced environment variable.

#### What the permissions cover

Token scopes apply across the server, not to individual constitution
names. A read token can read any constitution available through that
server's MCP tools. A write token can also change any of those
constitutions. Selecting `constitution_key="customer-support"` when creating a binder
chooses what it reads; it is not an access restriction.

Do not use constitution names as a privacy boundary between teams or
customers. Where separate access boundaries are required, use separately
isolated deployments and credentials. Deliberately published constitution
pages remain public regardless of token scope.

HTTP token checks do not protect direct database access. Local CLI
commands, an embedded control plane, and stdio operate with the access
of their host process. Keep workspace and database access outside the
agent environment if HTTP read scope is the boundary you rely on.
`allow_insecure = true` removes the HTTP token boundary entirely.

#### Approval and attribution are different

Authentication establishes which live credential a request used and
whether its scope permits the tool. It does not establish that the new
mission or principles are sensible, safe, or reviewed.

The remote CLI's confirmation questions help an operator review an
apply. They are not a server-enforced approval workflow. Another client
with a write token can call `apply_direction` without answering them.
Review requirements belong in the surrounding deployment process and
in who can obtain its write credentials.

Read version attribution with these limits in mind:

| Field | What it records | What it does not prove |
| --- | --- | --- |
| `created_by` | The actor name supplied by the client. | The identity of the person who made the request. |
| `authorized_by` | The client's reported approval method: `operator`, `automation`, or `override`. | That a human approved the change or a trusted pipeline performed it. |
| `token_id` | For an authenticated HTTP write, the credential verified by the server. | Who physically used that credential or whether its holder was authorized by your organization to make this particular change. |

Local writes have no authenticated HTTP token identity. Keep external
review or deployment records if you need evidence of approval, and use
separate credentials for independently operated writers so their requests
can be distinguished.

Revoking a token stops subsequent authenticated requests using it. It
does not remove direction already cached by agents, cancel running work,
or undo completed actions. A read failure may still use cached direction
under the application's [configured failure policy](adapters.md#inspecting-binding-status).

### Minting and revoking tokens

The store keeps a token inventory in its own table, managed from the
workspace:

```bash
kyno token add ci --scope write               # prints the value, once
kyno token add hotfix --scope write --ttl 2h  # expires on its own
kyno token list                               # live tokens
kyno token list --all                         # revoked and expired included
kyno token revoke ci
kyno token revoke --id 3                      # when two live tokens share a name
```

The rules, one at a time:

- `--scope` is required; there is no default. `read` allows every tool
  except `apply_direction`; `write` allows everything.
- The value is printed once, at minting, and starts with `kyno_` so a
  leaked one is recognizable, by people and by secret scanners. Only its
  sha256 is stored: steal the database and you hold hashes, and a hash
  does not work as a token.
- Names are labels, not identities. Two live tokens share a name during
  rotation on purpose, and commands ask for `--id` when a name is
  ambiguous.
- Rows are never deleted. Revoking sets a timestamp on the row, and
  `revoke` acts on live tokens only: a token that already expired is
  refused, so the row keeps showing how it died.
- The `token` commands are local, like `kyno db init`: they talk straight
  to the workspace's database. There is no way to mint over the network --
  if a stolen write token could mint, it could mint itself a spare before
  you revoke it.

On every authenticated request, the server writes one log line per tool
call — the token id and name, the tool, and the constitution. That log is
the request history: read it to know which tokens were active in a time
window.

A remote write also records the token on the version it appends. Three
fields say three different things about a version, and only the last one
is checked by the server: `created_by` is the actor the client claimed,
`authorized_by` is how the client says the apply was approved (`operator`,
`automation` or `override`), and the token id is the credential the server itself
verified from the request. A local apply has no token, so that field
stays empty.

The token's `last_used_at` is also updated, at most once every five
minutes, so `kyno token list` can answer whether a token is still in use
without a database write per request. The stored time can run up to five
minutes behind the real last use, never ahead; for exact times, read the
log.

## Remote mode

Locally, `kyno` talks straight to a store file on your disk. Remote mode points the same commands at a Kyno server instead: you operate production from your laptop or a pipeline, and nobody holds database credentials. Setting it up consists in three steps: save a token, name a destination, and go remote with the commands you already know.

### 1. Save a token

Each credentials profile holds one token. The token itself never goes on the command line, because command lines end up in shell history:

```bash
kyno credentials add --token-env KYNO_TOKEN                   # profile "default"
kyno credentials add --profile oncall --token-env KYNO_ONCALL # a second identity
kyno credentials add --profile laptop                         # no flag: asks for it, hidden
```

`--token-env` stores a reference (`${KYNO_TOKEN}`), read each time you use the profile — so rotating the token is just changing the variable's value. Without it, the token you type is written into the file, and the file is readable only by you.

`kyno credentials list` prints the profiles this machine holds, one line each. Token values never print: a stored token shows as `stored token`, and a profile that reads a variable shows the variable's name and whether it is set right now.

Everything lands in small files under `~/.kyno`, the same path on every machine, written only by these commands. They never live next to a repo, so a credentials file can't end up in a commit by mistake.

### 2. Name a destination

Each remote profile is one destination: the URL, and where its token comes from.

```bash
kyno remote add --url https://kyno.mybiz.com                          # "default", on the default credentials
kyno remote add --url https://kyno.mybiz.com --profile oncall --credentials oncall
kyno remote add --url https://kyno.mybiz.com --profile ci --token-env KYNO_TOKEN
```

Pointing at credentials that don't exist fails right there, and the error tells you what you do have and what to run. The `--token-env` form skips the credentials file entirely — right for a CI image that carries no credentials at all.

A profile has exactly one token source. Several profiles can share one credential (three regional servers, one operator token), but one profile never holds two tokens — Kyno would be picking between them silently, and "who wrote this" would become a guess. To act as someone else on the same server, make a second profile with the same URL and different credentials; a production write then visibly says which profile it used.

### 3. Go remote

One flag, on the commands you already use:

```bash
kyno current --remote
kyno get-version 2 --remote --yaml
kyno apply constitution.yaml --note "sharpen the mission" --remote
kyno check constitution.yaml --remote
kyno history --remote
kyno export --remote
kyno whoami --remote
```

They work against the profile's endpoint instead of your local store and print exactly what their local versions print. `--profile oncall` picks a different remote profile; `--credentials` or `--token-env` beside it swaps the token source for that one run. Without `--remote` you are always on your local store — there is no fallback in either direction.

When you run a remote `apply` from a terminal, Kyno asks a question after showing the delta: have you evaluated this change against your workflow? The default answer is no, and if the answer is no, nothing is applied. If the file has the same content as an older version, Kyno also asks whether this is a deliberate revert, to catch applies from stale files.

Two flags skip the questions, with two different meanings, and you pass at most one:

| flags | questions | meaning |
|---|---|---|
| none (terminal) | asked | a person answered |
| `--no-interactive` | skipped | nobody was there; the checks are the protection |
| `--unsafe-approval` | skipped, yes to all | approved blind, on purpose |

`--no-interactive` is the CI lane: the yes already happened in review, and the version pin plus the `check` step do the guarding. `--unsafe-approval` is for overriding on purpose, and it stands out in review by design.

Who stood behind an apply is recorded on the version it writes as `authorized_by` — `operator`, `automation`, or `override` — and `kyno history` prints it. It's written at write time because it can't be reconstructed later. Local applies record nothing: there were no questions to answer.

Two behaviors worth knowing. A remote `apply` fetches the server's head and shows you the same delta a local apply shows, before it applies; a duplicate apply is the same clean no-op. And a server you can't reach is a plain one-line error — except under `check`, which still prints its field-by-field report and ends with a comparison line saying the store was not compared, and why.

`check` exits 0 only when the file matches the current direction. It exits 1 when direction differs, the constitution has no versions, or the comparison fails, including an unreachable local store or remote server. The field report still prints when the comparison fails.

### Checking your wiring

A profile is a pointer to a pointer: the remote points at credentials, the credentials point at a variable, the variable holds the token. `kyno remote show` walks the whole chain so you never have to:

```console
$ kyno remote show --profile ci
profile: ci
url: https://kyno.mybiz.com
token from: ${KYNO_TOKEN}
resolves: no (remote profile 'ci' reads its token from ${KYNO_TOKEN}, which is not set)
```

The token itself is never shown. A profile that doesn't resolve exits 1 and the reason names the fix, so `remote show` can gate a setup script. `kyno remote list` prints one line per profile.

`remote show` answers a local question: does this chain resolve on my machine. `kyno whoami --remote` answers the other half, which only the server can: which token it sees behind your requests, and what that token is allowed to do.

```console
$ kyno whoami --remote
camilo  write
```

It is remote only, because a local store has no request to look at. Against a server running with `allow_insecure` it prints `no token: the server accepted the request without checking for one`, which is how you find out the endpoint you are talking to checks nothing.

## Deploying

- Deploying is putting the workspace on the host and running
  `kyno serve` in it. Paths in `config/server` resolve against the
  workspace, never against whatever directory the process starts in.
- Run a hosted Kyno behind a reverse proxy that enforces rate limits.
  The public pages answer anonymous traffic, and rate limiting is the
  proxy's job, not Kyno's.
- Field sizes are part of the API contract: mission ≤ 4,000 characters,
  declaration ≤ 200,000, change note ≤ 2,000, up to 100 principles with
  titles ≤ 300 and descriptions ≤ 4,000, constitution names ≤ 200.
  `apply_direction` refuses anything larger, and `/mcp` request bodies are
  capped at 5 MB.
- A pip-installed Kyno ships with its own migration scripts: `kyno db init`
  creates a fresh schema stamped at the current head, and `kyno db upgrade`
  brings an existing database up to date after an upgrade.

## Testing

```bash
python -m pytest -q                      # SQLite, no network
KYNO_TEST_POSTGRES_URL=postgresql+psycopg://… python -m pytest -q   # + Postgres
python -m pytest -q --cov=kyno --cov-fail-under=90   # what CI runs before a merge
```

The coverage gate keeps line coverage above 90%, and CI fails a change that drops below it. The gate only guards quantity; the bar for the tests themselves stays the same: one specific case per test, named `given_{x}_when_{y}_then_{z}`.

## 💬 Questions?

[Ask one](https://github.com/cizambra/kyno/issues/new?template=question.yml)
and I'll answer there, so the next person finds it too.
