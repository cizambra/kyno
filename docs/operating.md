# Operating Kyno

Storage, auth, deployment, and testing for a production Kyno.

On this page:

- [Storage](#storage)
- [Running Kyno embedded](#running-kyno-embedded)
- [Auth](#auth)
- [Deploying](#deploying)
- [Testing](#testing)


## Storage

SQLite out of the box; PostgreSQL for production via `KYNO_DATABASE_URL`.
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

store = store_from_settings(Settings.from_env())  # reads KYNO_DATABASE_URL
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
  unless you explicitly opt in (`KYNO_ALLOW_INSECURE_HTTP`, for local
  experimentation only; it warns), and a `KYNO_TOKEN` that's set but blank
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

## Remote profiles

To work against a hosted Kyno from your laptop or a pipeline you need two things: where the server is, and which token to show it. Both live in small files under `~/.kyno`, the same path on every machine, and only the commands below write them. They never live next to a repo, so a credentials file can't end up in a commit by mistake.

Start with credentials. Each profile holds one token, and the token itself never goes on the command line:

```bash
kyno credentials add --token-env KYNO_TOKEN                   # profile "default"
kyno credentials add --profile oncall --token-env KYNO_ONCALL # a second one
kyno credentials add --profile laptop                         # no flag: asks for it, hidden
```

`--token-env` doesn't store the token; it stores a reference (`${KYNO_TOKEN}`) that gets read when you use the profile, so rotating the token is just changing the variable's value. Without it, the token you type is written into the file, and the file is readable only by you.

Then remotes. Each profile is one destination: the URL, and where its token comes from.

```bash
kyno remote add --url https://kyno.mybiz.com                          # "default", on the default credentials
kyno remote add --url https://kyno.mybiz.com --profile oncall --credentials oncall
kyno remote add --url https://kyno.mybiz.com --profile ci --token-env KYNO_TOKEN
```

If you point a remote at credentials that don't exist, the command fails right there and tells you what you do have and what to run. `--token-env` on a remote skips the credentials file entirely, which is what you want in a CI image that carries no credentials at all.

A profile is configuration that points at other configuration: the remotes file points at a credentials profile, the credentials profile points at a variable, and the variable holds the token. When something breaks, reading one file isn't enough — you'd have to walk all three hops yourself. `kyno remote show --profile X` walks them for you: it prints the URL, where the token comes from, and whether the whole chain resolves right now, with the token itself never shown. `kyno remote list` prints one line per profile. If a profile doesn't resolve, `show` exits 1 and the reason includes the command that fixes it, so you can put it in a setup script and let it gate.

A profile has exactly one token source. Several profiles can share one credential — say three regional servers that all accept the same operator token — but one profile never holds two tokens, because Kyno would be picking between them silently and "who wrote this" would become a guess. If you want to act as someone else on the same server, make a second profile with the same URL and different credentials; a production write then visibly says which profile it used.

## Deploying

- Use an absolute `KYNO_DATABASE_URL` in production. The default
  (`sqlite:///kyno.sqlite3`) is a dev convenience that resolves against
  whatever working directory the process starts in.
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
```

## 💬 Questions?

[Ask one](https://github.com/cizambra/kyno/issues/new?template=question.yml)
and I'll answer there, so the next person finds it too.
