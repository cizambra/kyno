from __future__ import annotations

import json
from datetime import UTC, datetime

from kyno.errors import ConfigError
from kyno.mcp_server import build_server
from kyno.models import WRITE
from kyno.public_page import PageConfig
from kyno.service import ControlPlane
from kyno.tokens import hash_value

# A JSON-RPC request is small. The largest legitimate one carries a full constitution, and the
# field size limits keep that well under this cap.
MAX_MCP_BODY_BYTES = 5_000_000


# Sent on every public response, including 404s. The pages carry one inline <style> block and
# nothing that runs, loads, or frames.
PUBLIC_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


def token_for_request(headers: dict, token_store, now: datetime):
    """Find the live token a request's bearer header carries, or None.

    Returns None in four cases: no Authorization header, a header that is
    not a Bearer value, a value no row matches, and a token that is revoked
    or expired. The caller turns None into a 401.

    The four cases return the same response on purpose. Distinguishing them
    would tell a caller which tokens exist."""
    value = None
    for k, v in headers.items():
        if k.lower() == "authorization":
            value = v
            break
    if value is None or not value.startswith("Bearer "):
        return None
    token = token_store.token_by_hash(hash_value(value[len("Bearer ") :]))
    if token is None or not token.live_at(now):
        return None
    return token


def _tool_calls(body: bytes) -> list[tuple[str, str]]:
    """List the (tool, constitution) pairs a JSON-RPC body asks for.

    Returns an empty list for a body that is not valid JSON, or that
    carries no tool call: rejecting malformed requests is the MCP layer's
    job, and this only reports what it can read.

    A JSON array (a batch) is read too, one pair per item. Batches are
    NOT supported. Do not build batch APIs on this: they will error, the
    MCP layer rejects arrays. The scope check reads the shape anyway so
    that a future SDK version that accepts batches cannot become a way
    past the read/write rule."""
    try:
        payload = json.loads(body)
    except ValueError:
        return []
    items = payload if isinstance(payload, list) else [payload]
    calls = []
    for item in items:
        if not isinstance(item, dict) or item.get("method") != "tools/call":
            continue
        params = item.get("params") or {}
        arguments = params.get("arguments") or {}
        name = params.get("name")
        if isinstance(name, str):
            calls.append((name, arguments.get("constitution") or "default"))
    return calls


async def run_stdio(control_plane: ControlPlane) -> None:
    from mcp.server.stdio import stdio_server

    server = build_server(control_plane)
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


class _McpEndpoint:
    """The ASGI app served at /mcp. On every request it checks the token,
    enforces the body size cap, applies the read/write rule, and only then
    hands the request to the MCP session manager.

    One instance serves every request; nothing request-specific is stored
    on self."""

    def __init__(self, manager, token_store):
        self._manager = manager
        self._token_store = token_store

    async def __call__(self, scope, receive, send):
        from starlette.responses import Response

        headers = {
            k.decode(errors="replace"): v.decode(errors="replace")
            for k, v in scope.get("headers", [])
        }
        token = None
        if self._token_store is not None:
            token = token_for_request(headers, self._token_store, datetime.now(UTC))
            if token is None:
                await Response("unauthorized", status_code=401)(scope, receive, send)
                return
        declared = headers.get("content-length", "")
        if declared.isdigit() and int(declared) > MAX_MCP_BODY_BYTES:
            await Response("request body too large", status_code=413)(scope, receive, send)
            return
        if scope.get("method") != "POST":
            # GET opens the server-sent-events stream, where the server
            # pushes notifications; DELETE closes a session. Neither
            # carries a tool call, so there is no scope to check and
            # nothing to log.
            await self._manager.handle_request(scope, receive, send)
            return
        body = await self._read_body(scope, receive, send)
        if body is None:
            return
        calls = _tool_calls(body)
        writes = any(name == "set_direction" for name, _ in calls)
        if token is not None and token.scope != WRITE and writes:
            await Response("forbidden: this token is read-only", status_code=403)(
                scope, receive, send
            )
            return
        await self._manager.handle_request(scope, _replayed(body, receive), send)

    async def _read_body(self, scope, receive, send) -> bytes | None:
        """Buffer the whole request body and return it, or return None
        after answering when the request cannot proceed.

        The body is buffered because the size cap needs the byte count and
        the read/write rule needs to see the tool name before the MCP
        layer runs. None means either the client disconnected mid-body
        (nothing was sent back) or the body crossed the size cap (a 413
        was sent).

        Each receive() returns one ASGI message. For a request body it is
        {"type": "http.request", "body": bytes, "more_body": bool}; any
        other type here means the client disconnected."""
        from starlette.responses import Response

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] != "http.request":
                return None
            body.extend(message.get("body") or b"")
            if len(body) > MAX_MCP_BODY_BYTES:
                await Response("request body too large", status_code=413)(scope, receive, send)
                return None
            if not message.get("more_body"):
                break
        return bytes(body)


def _replayed(body: bytes, receive):
    """A receive callable that hands the MCP layer the buffered body first,
    then continues with the real channel (disconnect messages and so on)."""
    delivered = False

    async def replay():
        nonlocal delivered
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": body, "more_body": False}
        return await receive()

    return replay


def build_http_app(
    control_plane: ControlPlane,
    token_store=None,
    page: PageConfig | None = None,
    *,
    allow_insecure: bool = False,
):
    """Build the Starlette app: the public constitution pages, and /mcp
    behind the token check.

    `token_store` is where bearer values are looked up; it only has to
    answer token_by_hash. Passing None turns the check off, which lets
    anyone who can reach the port rewrite the constitution, so it
    requires allow_insecure=True."""
    if token_store is None and not allow_insecure:
        raise ConfigError(
            "refusing to build an HTTP app without a token store: "
            "pass the store, or pass allow_insecure=True to open the write endpoint"
        )
    from contextlib import asynccontextmanager

    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from starlette.applications import Starlette
    from starlette.responses import HTMLResponse, JSONResponse
    from starlette.routing import Mount, Route

    from kyno.public_page import render_constitution, render_index, render_not_found

    page = page or PageConfig()

    server = build_server(control_plane)
    try:
        # The MCP layer has its own body cap (4 MiB by default) that would answer 413 below
        # ours, so one constant sets both.
        manager = StreamableHTTPSessionManager(app=server, max_request_body_size=MAX_MCP_BODY_BYTES)
    except TypeError:  # an mcp release before the cap existed
        manager = StreamableHTTPSessionManager(app=server)

    handle = _McpEndpoint(manager, token_store)

    # Unpublished and unknown return the same response, and never 401: a 401 would tell an
    # anonymous caller that a name they guessed is real. These are sync on purpose -- Starlette
    # runs a plain `def` endpoint in a threadpool, so their blocking store reads stay off the
    # event loop.
    def constitution_page(request):
        view = control_plane.public_constitution(request.path_params["name"])
        if view is None:
            return HTMLResponse(render_not_found(page), status_code=404, headers=PUBLIC_HEADERS)
        return HTMLResponse(render_constitution(view, page), headers=PUBLIC_HEADERS)

    def constitution_json(request):
        view = control_plane.public_constitution(request.path_params["name"])
        if view is None:
            return JSONResponse({"error": "not found"}, status_code=404, headers=PUBLIC_HEADERS)
        return JSONResponse(view.to_dict(), headers=PUBLIC_HEADERS)

    def index_page(request):
        listed = control_plane.published_constitutions()
        return HTMLResponse(render_index(listed, page), headers=PUBLIC_HEADERS)

    def index_json(request):
        listed = control_plane.published_constitutions()
        return JSONResponse(
            {"constitutions": [v.to_summary() for v in listed]}, headers=PUBLIC_HEADERS
        )

    @asynccontextmanager
    async def lifespan(app):
        async with manager.run():
            yield

    # Order matters: "{name}" would otherwise match "default.json" as a name. The index is at
    # /constitutions.json, not /constitutions/index.json, so a constitution named "index" keeps
    # its own page.
    routes = [
        Route("/constitutions.json", index_json),
        Route("/constitutions/", index_page),
        Route("/constitutions/{name}.json", constitution_json),
        Route("/constitutions/{name}", constitution_page),
        Mount("/mcp", app=handle),
    ]
    return Starlette(routes=routes, lifespan=lifespan)
