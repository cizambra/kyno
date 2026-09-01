# Operating Kyno

Storage, auth, deployment, and testing for a production Kyno.

On this page:

- [The workspace](#the-workspace)
- [Storage](#storage)
- [Running Kyno embedded](#running-kyno-embedded)
- [Auth](#auth)
- [Deploying](#deploying)
- [Testing](#testing)


## The workspace

A workspace is a directory that defines one Kyno instance. `kyno new`
creates it, and every command that needs the store finds it by walking
up from the current directory, the way git does.

```console
$ kyno new acme
$ cd acme && kyno init-db && kyno serve --transport http
```

Two directories, two owners:

- `~/.kyno` holds what belongs to a person: credentials and remotes. It
  never ships with a deploy.
- The workspace holds what belongs to the instance: `config/server` and,
  on SQLite, the store under `db/`.

The rules for `config/server`:

- A value is written in, or is one `${VAR}` reference to an environment
  variable you named. References resolve at startup; an unset variable
  fails startup and the error names the variable.
- Secrets only enter as references, so the workspace is safe to commit
  and to mount on a host.
- An unknown key or section fails startup and names the typo.

The `[database]` section describes the database with split keys, like
Rails' `database.yml`. The facts are written in; the password is the one
reference:

```ini
[database]
adapter = postgresql
host = db.internal
database = kyno
username = kyno
password = ${DB_PASSWORD}
```

- The default, as `kyno new` writes it: `adapter = sqlite3` with the
  store at `db/kyno.sqlite3`. This runs production on a single box.
- A platform that hands you one connection string uses
  `url = ${DATABASE_URL}` instead. `url` beside the split keys is
  refused.

## Storage

SQLite out of the box; PostgreSQL for production -- both declared in the
workspace's `[database]` section.
Storage is pluggable: hand `SqlConstitutionStore` your own SQLAlchemy
`Engine` to live inside an existing database, or implement the small store
protocol to bring your own persistence entirely. Concurrent writers are safe:
versions are serialized by a unique index and a retry, never lost or
duplicated.

Reads never fail on an empty store. Before any direction is set, consumers
get a version-0 empty state, so integrating Kyno ahead of adopting it costs
nothing.

## Running Kyno embedded

When your orchestrator is itself a Python app, you can run the control
plane inside it instead of behind `kyno serve`. The construction mirrors
what the CLI does: read the settings, build the store, and hand the
control plane to the binder.

```python
from kyno.config import Settings, store_from_settings
from kyno.service import ControlPlane
from kyno.sdk import DirectionBinder, LocalDirectionSource

store = store_from_settings(Settings.load())  # finds the workspace at or above cwd
control_plane = ControlPlane(store)
binder = DirectionBinder(LocalDirectionSource(control_plane))
```

The schema has to exist before the first read, so run `kyno init-db` once
against the same database, or call `store.create_all()` from code. From
here the binder behaves exactly as it does over MCP, and the CLI keeps
working against the same database for edits and inspection.

## Auth

- **stdio** is open. A process that can spawn the server already owns the
  database file under it, so a token there would add a step without adding
  protection.
- **HTTP** is gated by a shared bearer token (`KYNO_TOKEN`) gates every request to the
  MCP endpoint (`/mcp`). The server refuses to start tokenless over HTTP
  unless you explicitly opt in (`allow_insecure = true` in
  `config/server`, for local experimentation only; it warns), and a
  `KYNO_TOKEN` that's set but blank
  is a configuration error rather than silently no auth. Embedders building
  the app in code opt in the same way:
  `build_http_app(..., allow_insecure=True)`. The published constitution
  pages above sit outside that gate on purpose; they are the surface you
  chose to open.

The write token is direction control: whoever holds it steers the
instructions of every agent bound to this Kyno. Treat it like a system-prompt
credential: serve `/mcp` over TLS and keep the token out of logs and
checkpoints (Kyno's own reprs never print it). One related caution: the
`[kyno:direction …]` header on the injected block is a record for reading
transcripts, not a security check. Text arriving from tools or users can
imitate it, so nothing should trust a block just for looking like one. Kyno
refuses constitution text containing the marker, and the adapters only ever
replace the block they injected themselves.

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
kyno set constitution.yaml --note "sharpen the mission" --remote
kyno check constitution.yaml --remote
kyno log --remote
kyno export --remote
```

They work against the profile's endpoint instead of your local store and print exactly what their local versions print. `--profile oncall` picks a different bundle; `--credentials` or `--token-env` beside it swaps the token source for that one run. Without `--remote` you are always on your local store — there is no fallback in either direction.

When you run a remote `set` from a terminal, Kyno asks a question after showing the delta: have you evaluated this change against your workflow? The default answer is no, and if the answer is no, nothing is applied. If the file has the same content as an older version, Kyno also asks whether this is a deliberate revert, to catch applies from stale files.

Two flags skip the questions, in two different spirits, and you pass at most one:

| flags | questions | meaning |
|---|---|---|
| none (terminal) | asked | a person answered |
| `--no-interactive` | skipped | nobody was there; the checks are the protection |
| `--unsafe-approval` | skipped, yes to all | approved blind, on purpose |

`--no-interactive` is the CI lane: the yes already happened in review, and the version pin plus the `check` step do the guarding. `--unsafe-approval` is for overriding on purpose, and it stands out in review by design.

Who stood behind an apply is recorded on the version it writes as `authorized_by` — `operator`, `automation`, or `override` — and `kyno log` prints it. It's written at write time because it can't be reconstructed later. Local applies record nothing: there were no questions to answer.

Two behaviors worth knowing. A remote `set` fetches the server's head and shows you the same delta a local set shows, before it applies; a duplicate apply is the same clean no-op. And a server you can't reach is a plain one-line error — except under `check`, where the field report still prints and the comparison line says why it didn't run.

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
  `set_direction` refuses anything larger, and `/mcp` request bodies are
  capped at 5 MB.
- A pip-installed Kyno ships with its own migration scripts: `kyno init-db`
  creates a fresh schema stamped at the current head, and `kyno upgrade-db`
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
