from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta

from kyno.errors import ConfigError
from kyno.mcp_server import build_server
from kyno.models import WRITE
from kyno.public_page import PageConfig
from kyno.service import ControlPlane
from kyno.tokens import hash_value

# A JSON-RPC request is small; the largest legitimate one carries a full
# constitution, which the field caps hold far under this.
MAX_MCP_BODY_BYTES = 5_000_000

# How often last_used_at is allowed to move. A token already marked as used
# in the last five minutes is not updated again, so a busy fleet costs one
# write per token every five minutes instead of one per request. In exchange,
# "last used" in `kyno token list` can run up to five minutes behind.
TOUCH_EVERY = timedelta(minutes=5)

# One line per tool call: token id and name, the tool, the constitution.
# Read this log to know what a token did and when; last_used_at only says
# whether a token is still in use at all.
_request_log = logging.getLogger("kyno.requests")


# On every public response, including 404s: the pages carry one inline
# <style> block and nothing else that runs, loads, or frames.
PUBLIC_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


def token_for_request(headers: dict, store, now: datetime):
    """Find the live token a request's bearer header carries, or None.
    No header, an unknown value, a revoked token and an expired one all
    return None, and the caller turns None into a 401. The four cases
    look identical from outside on purpose: a different answer would
    tell a caller which tokens exist."""
    value = None
    for k, v in headers.items():
        if k.lower() == "authorization":
            value = v
            break
    if value is None or not value.startswith("Bearer "):
        return None
    token = store.token_by_hash(hash_value(value[len("Bearer ") :]))
    if token is None or not token.live_at(now):
        return None
    return token


def _tool_calls(body: bytes) -> list[tuple[str, str]]:
    """The (tool, constitution) pairs a JSON-RPC body asks for. A body
    that is not valid JSON, or carries no tool call, returns an empty
    list -- rejecting malformed requests is the MCP layer's job, not
    this function's."""
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


def build_http_app(
    control_plane: ControlPlane,
    store=None,
    page: PageConfig | None = None,
    *,
    allow_insecure: bool = False,
):
    """The Starlette app: the public constitution pages, and /mcp checking
    bearer values against the store's token table. No store means no gate --
    anyone who can reach the port can rewrite the constitution -- so an
    embedder opts into that in code, as loudly as the CLI's allow_insecure."""
    if store is None and not allow_insecure:
        raise ConfigError(
            "refusing to build an HTTP app without a token store: "
            "pass the store, or pass allow_insecure=True to open the write endpoint"
        )
    from contextlib import asynccontextmanager

    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from starlette.applications import Starlette
    from starlette.responses import HTMLResponse, JSONResponse, Response
    from starlette.routing import Mount, Route

    from kyno.public_page import render_constitution, render_index, render_not_found

    page = page or PageConfig()

    server = build_server(control_plane)
    try:
        # The MCP layer grew its own body cap (4 MiB by default) that would
        # answer 413 below ours; one constant governs both layers.
        manager = StreamableHTTPSessionManager(app=server, max_request_body_size=MAX_MCP_BODY_BYTES)
    except TypeError:  # an mcp release before the cap existed
        manager = StreamableHTTPSessionManager(app=server)

    async def handle(scope, receive, send):
        headers = {
            k.decode(errors="replace"): v.decode(errors="replace")
            for k, v in scope.get("headers", [])
        }
        token = None
        if store is not None:
            token = token_for_request(headers, store, datetime.now(UTC))
            if token is None:
                await Response("unauthorized", status_code=401)(scope, receive, send)
                return
            store.touch_token(token.id, older_than=datetime.now(UTC) - TOUCH_EVERY)
        declared = headers.get("content-length", "")
        if declared.isdigit() and int(declared) > MAX_MCP_BODY_BYTES:
            await Response("request body too large", status_code=413)(scope, receive, send)
            return
        if scope.get("method") != "POST":
            # GET opens the SSE stream and DELETE closes a session; neither
            # carries a tool call, so the gate above is all they need.
            await manager.handle_request(scope, receive, send)
            return
        # Buffer the body: the cap needs counting either way, and the scope
        # check has to see the tool name before the MCP layer runs.
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] != "http.request":
                # The client hung up before finishing the body.
                return
            body.extend(message.get("body") or b"")
            if len(body) > MAX_MCP_BODY_BYTES:
                await Response("request body too large", status_code=413)(scope, receive, send)
                return
            if not message.get("more_body"):
                break
        calls = _tool_calls(bytes(body))
        if token is not None:
            if token.scope != WRITE and any(name == "set_direction" for name, _ in calls):
                await Response("forbidden: this token is read-only", status_code=403)(
                    scope, receive, send
                )
                return
            for name, constitution in calls:
                _request_log.info(
                    "token=%s name=%s tool=%s constitution=%s",
                    token.id,
                    token.name,
                    name,
                    constitution,
                )
        replayed = False

        async def replay():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await manager.handle_request(scope, replay, send)

    # Unpublished and unknown answer identically, and never 401: a 401 would
    # tell an anonymous caller that a name it guessed is real. These are sync
    # on purpose -- Starlette runs a plain `def` endpoint in a threadpool, so
    # their blocking store reads stay off the event loop.
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

    # Order matters: "{name}" would otherwise swallow "default.json" whole.
    # The index sits at /constitutions.json, not /constitutions/index.json,
    # so a constitution actually named "index" keeps its own page.
    routes = [
        Route("/constitutions.json", index_json),
        Route("/constitutions/", index_page),
        Route("/constitutions/{name}.json", constitution_json),
        Route("/constitutions/{name}", constitution_page),
        Mount("/mcp", app=handle),
    ]
    return Starlette(routes=routes, lifespan=lifespan)
