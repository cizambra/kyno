# MCP Registry listing

Kyno is published under `io.github.cizambra/kyno`. The listing in
`server.json` describes the PyPI package and its local stdio transport.
HTTP deployments are self-hosted; the listing does not advertise a shared
public endpoint.

## Set up the local server

The registry launch command needs an existing workspace with an initialized
database. Create one before configuring your MCP client:

```bash
pip install kyno
kyno new acme
cd acme
kyno db init
```

Supply the absolute path to `acme` for the listing's `workspace` variable.
The client runs `uvx` with `--directory` so Kyno finds that workspace even
when the client starts elsewhere. The package arguments are
`serve --transport stdio`.

To verify the setup yourself, run from outside the workspace:

```bash
uvx --directory /absolute/path/to/acme kyno==1.0.1 serve --transport stdio
```

The process waits for an MCP client on standard input. Apply your mission
and principles from the workspace using the README's quick start.

## Publish a release

The package README includes the Registry's ownership marker:

```markdown
<!-- mcp-name: io.github.cizambra/kyno -->
```

Keep it in the README; the Registry checks the description published to
PyPI. The release workflow tests and uploads the package first, then
publishes its listing using GitHub OIDC. No Registry token secret is needed.
The publishing job derives the listing version from `pyproject.toml`.

Before a release, update the package version in `pyproject.toml` and both
version fields in `server.json`. Create the matching `v` tag as usual.
For this listing's first release, use `v1.0.1`.

If the Registry job fails after PyPI succeeds, rerun only the failed job;
do not republish the same package files to PyPI.

PulseMCP currently pauses submissions and says it will import official
Registry entries when submissions reopen. Its current status is available
at https://www.pulsemcp.com/submit.
