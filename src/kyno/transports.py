from __future__ import annotations

from kyno.errors import ConfigError
from kyno.mcp_endpoint import MAX_MCP_BODY_BYTES, McpEndpoint
from kyno.mcp_server import build_server
from kyno.public_page import PageConfig
from kyno.service import ControlPlane

# Sent on every public response, including 404s. The pages carry one inline <style> block and
# nothing that runs, loads, or frames.
PUBLIC_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


async def run_stdio(control_plane: ControlPlane) -> None:
    from mcp.server.stdio import stdio_server

    server = build_server(control_plane)
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


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

    handle = McpEndpoint(manager, token_store)

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
