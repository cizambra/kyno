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
creates it; the argument is the name of the directory to create, so pick
any name you like. Every command that needs the store finds the
workspace by walking up from the current directory, the way git does.

```console
$ kyno new my-instance
$ cd my-instance && kyno db init && kyno serve --transport http
```

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
section. Which engine runs where is the operator's call: SQLite handles
a single-box production, and the others work for local development if
that is your setup. If you want postgres or mysql, you need to install
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
  `set_direction`; `set_direction` needs `write` and answers 403
  otherwise. A server with no live tokens starts and
  serves, refusing every /mcp request until one is minted; a note on
  stderr says so at startup. Because the check reads the database on
  every request, a token minted while the server runs works immediately.
  To turn the check off entirely, opt in with `allow_insecure = true` in
  `config/server` (for local experimentation only; it warns). Embedders building the app in
  code pass their store — `build_http_app(cp, token_store=store)` — or opt in
  the same way:
  `build_http_app(cp, allow_insecure=True)`. The published constitution
  pages above sit outside that gate on purpose; they are the surface you
  chose to open.

A write token is direction control: whoever holds it steers the
instructions of every agent bound to this Kyno. Treat it like a system-prompt
credential: serve `/mcp` over TLS and keep the token out of logs and
checkpoints (Kyno's own reprs never print it). One related caution: the
`[kyno:direction …]` header on the injected block is a record for reading
transcripts, not a security check. Text arriving from tools or users can
imitate it, so nothing should trust a block just for looking like one. Kyno
refuses constitution text containing the marker, and the adapters only ever
replace the block they injected themselves.

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
  except `set_direction`; `write` allows everything.
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
