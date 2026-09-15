"""MCP resource discovery, reads, and change notifications."""

import asyncio
import json

import mcp.types as types
from mcp.server import Server
from pydantic import AnyUrl

from kyno.mcp_handlers import handle_get_constitution
from kyno.mcp_request_context import record_response
from kyno.service import ControlPlane
from kyno.wire import RESOURCE_URI


def register_resources(server: Server, control_plane: ControlPlane, token_store=None) -> None:
    subscribers: set = set()
    pending: set = set()

    @server.list_resources()
    async def list_resources() -> list[types.Resource]:
        return [
            types.Resource(
                uri=AnyUrl(RESOURCE_URI), name="current constitution", mimeType="application/json"
            )
        ]

    # One URI cannot stand for several constitutions, so the resource is the control plane's
    # default one, served compact (a resource takes no parameters). A new version of any
    # constitution notifies here; agents then read by name with the tools.
    @server.read_resource()
    async def read_resource(uri: AnyUrl) -> str:
        if str(uri) != RESOURCE_URI:
            raise ValueError(f"unknown resource: {uri}")
        result = handle_get_constitution(control_plane)
        record_response(server, control_plane, token_store, result, "read_resource", {})
        return json.dumps(result)

    @server.subscribe_resource()
    async def subscribe_resource(uri: AnyUrl) -> None:
        if str(uri) == RESOURCE_URI:
            subscribers.add(server.request_context.session)

    @server.unsubscribe_resource()
    async def unsubscribe_resource(uri: AnyUrl) -> None:
        subscribers.discard(server.request_context.session)

    # When a version is saved, subscribed clients must be told
    # ("resources/updated"). If we're already inside the server's event
    # loop, schedule the send there. If no loop is running (e.g. a plain
    # CLI write), there are no async subscribers in this process either.
    async def _send_update(session) -> None:
        try:
            await session.send_resource_updated(AnyUrl(RESOURCE_URI))
        except Exception:
            subscribers.discard(session)

    def _notify(_version) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        for session in list(subscribers):
            task = loop.create_task(_send_update(session))
            pending.add(task)
            task.add_done_callback(pending.discard)

    control_plane.on_change(_notify)
    server._kyno_subscribers = subscribers
    server._kyno_pending = pending
