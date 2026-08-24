# Operating Kyno

Storage, auth, deployment, and testing, for when Kyno moves past a
laptop.

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

## Auth

- **stdio** is open. A process that can spawn the server already owns the
  database file under it, so a token there would add a step without adding
  protection.
- **HTTP** is gated by a shared bearer token (`KYNO_TOKEN`) gates every request to the
  MCP endpoint (`/mcp`). The server refuses to start tokenless over HTTP
  unless you explicitly opt in (`KYNO_ALLOW_INSECURE_HTTP`, for local
  experimentation only; it warns), and a `KYNO_TOKEN` that is set but blank
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
- A pip-installed Kyno carries its own migration scripts: `kyno init-db`
  creates a fresh schema stamped at the current head, and `kyno upgrade-db`
  brings an existing database up to date after an upgrade.

## Testing

```bash
python -m pytest -q                      # SQLite, no network
KYNO_TEST_POSTGRES_URL=postgresql+psycopg://… python -m pytest -q   # + Postgres
```
