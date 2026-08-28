from __future__ import annotations

import hmac

from kyno.errors import ConfigError
from kyno.mcp_server import build_server
from kyno.public_page import PageConfig
from kyno.service import ControlPlane

# A JSON-RPC request is small; the largest legitimate one carries a full
# constitution, which the field caps hold far under this.
MAX_MCP_BODY_BYTES = 5_000_000


class _BodyOverCap(Exception):
    """Raised from the wrapped ASGI receive when the streamed body passes the cap."""


# On every public response, including 404s: the pages carry one inline
# <style> block and nothing else that runs, loads, or frames.
PUBLIC_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


def resolve_scope(
    headers: dict, token: str | None, read_tokens: tuple[str, ...] = ()
) -> str | None:
    """What the bearer header entitles this request to: "write", "read", or
    None for unauthorized. A server with no tokens configured is open, so
    every request is a write."""
    if token is None and not read_tokens:
        return "write"
    value = None
    for k, v in headers.items():
        if k.lower() == "authorization":
            value = v
            break
    if value is None:
        return None
    try:
        if token is not None and hmac.compare_digest(value, f"Bearer {token}"):
            return "write"
        for read_token in read_tokens:
            if hmac.compare_digest(value, f"Bearer {read_token}"):
                return "read"
        return None
    except TypeError:
        # Python's constant-time comparison only accepts plain-ASCII strings.
        # A header it can't even compare cannot be our token — so answer
        # "wrong token" (401), never "server error" (500).
        return None


async def run_stdio(control_plane: ControlPlane) -> None:
    from mcp.server.stdio import stdio_server

    server = build_server(control_plane)
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def build_http_app(
    control_plane: ControlPlane,
    token: str | None,
    page: PageConfig | None = None,
    *,
    read_tokens: tuple[str, ...] = (),
    allow_insecure: bool = False,
):
    """The Starlette app: the public constitution pages, and /mcp behind
    bearer tokens. The write token can do everything; a read token reaches
    every read tool and no set_direction. No tokens means anyone who can
    reach the port can rewrite the constitution, so an embedder opts into
    that in code, as loudly as the CLI's KYNO_ALLOW_INSECURE_HTTP."""
    if token is None and not allow_insecure:
        raise ConfigError(
            "refusing to build an HTTP app without a token: "
            "pass one, or pass allow_insecure=True to open the write endpoint"
        )
    for read_token in read_tokens:
        if token is not None and read_token == token:
            raise ConfigError(
                "a read token equals the write token: a token has one scope, "
                "so give the read side its own value"
            )
    from contextlib import asynccontextmanager

    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from starlette.applications import Starlette
    from starlette.responses import HTMLResponse, JSONResponse, Response
    from starlette.routing import Mount, Route

    from kyno.public_page import render_constitution, render_index, render_not_found

    page = page or PageConfig()

    def make_manager(read_only: bool):
        server = build_server(control_plane, read_only=read_only)
        try:
            # The MCP layer grew its own body cap (4 MiB by default) that
            # would answer 413 below ours; one constant governs both layers.
            return StreamableHTTPSessionManager(
                app=server, max_request_body_size=MAX_MCP_BODY_BYTES
            )
        except TypeError:  # an mcp release before the cap existed
            return StreamableHTTPSessionManager(app=server)

    write_manager = make_manager(read_only=False)
    read_manager = make_manager(read_only=True) if read_tokens else None

    async def handle(scope, receive, send):
        headers = {
            k.decode(errors="replace"): v.decode(errors="replace")
            for k, v in scope.get("headers", [])
        }
        request_scope = resolve_scope(headers, token, read_tokens)
        if request_scope is None:
            await Response("unauthorized", status_code=401)(scope, receive, send)
            return
        manager = read_manager if request_scope == "read" else write_manager
        declared = headers.get("content-length", "")
        if declared.isdigit() and int(declared) > MAX_MCP_BODY_BYTES:
            await Response("request body too large", status_code=413)(scope, receive, send)
            return
        seen = 0
        responded = False  # the MCP layer has started answering
        refused = False  # this exchange ended at our 413

        async def counted_receive():
            # Chunked transfer declares no length up front, so the cap is
            # also enforced while the body streams in. The 413 goes out here,
            # before the MCP layer can answer the aborted read itself.
            nonlocal seen, refused
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body") or b"")
                if seen > MAX_MCP_BODY_BYTES:
                    if not responded:
                        refused = True
                        await Response("request body too large", status_code=413)(
                            scope, receive, send
                        )
                    raise _BodyOverCap()
            return message

        async def guarded_send(message):
            nonlocal responded
            if refused:
                return
            responded = True
            await send(message)

        try:
            await manager.handle_request(scope, counted_receive, guarded_send)
        except* _BodyOverCap:
            pass

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
        async with write_manager.run():
            if read_manager is None:
                yield
            else:
                async with read_manager.run():
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
