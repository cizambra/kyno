from __future__ import annotations

import asyncio
import json

import mcp.types as types
from mcp.server import Server
from pydantic import AnyUrl

from kyno.errors import CoherenceError
from kyno.mcp_tools import PRINCIPLES_DETAIL_LEVELS, TITLES, TOOLS
from kyno.models import COMPACT, FULL, check_detail
from kyno.sdk.client import RESOURCE_URI as RESOURCE_URI  # the SDK owns the wire name
from kyno.service import ControlPlane
from kyno.tokens import hash_value


def check_principles_detail(detail: str) -> str:
    if detail not in PRINCIPLES_DETAIL_LEVELS:
        raise ValueError(
            f"unknown detail '{detail}': choose one of {', '.join(PRINCIPLES_DETAIL_LEVELS)}"
        )
    return detail


def _guard(fn):
    try:
        return fn()
    except CoherenceError as exc:
        raise ValueError(str(exc)) from exc


def _require(arguments: dict, key: str) -> None:
    if key not in arguments:
        raise ValueError(f"missing required argument: {key}")


# Reads default to compact. The declaration and the descriptions are the long text, and an agent
# that pulls before every step would pay for them every time. One argument asks for them.
def handle_get_constitution(
    cp: ControlPlane, constitution: str | None = None, detail: str = COMPACT
) -> dict:
    check_detail(detail)
    return _guard(lambda: cp.current(constitution).to_dict(detail))


def handle_get_changes_since(
    cp: ControlPlane,
    known_version: int,
    constitution: str | None = None,
    detail: str = COMPACT,
) -> dict:
    check_detail(detail)
    return _guard(lambda: cp.changes_since(known_version, constitution).to_dict(detail))


# The targeted reads: after pulling the titles, fetch the one piece that matters instead of the
# whole document again. Each answers with the version it came from, so answers can be combined:
# two answers on the same version describe the same document.
def handle_export_versions(
    cp: ControlPlane,
    constitution: str | None = None,
    from_version: int | None = None,
    to_version: int | None = None,
) -> list[dict]:
    return _guard(
        lambda: cp.export_versions(constitution, from_version=from_version, to_version=to_version)
    )


def handle_get_mission(cp: ControlPlane, constitution: str | None = None) -> dict:
    def read() -> dict:
        head = cp.current(constitution)
        return {"version": head.version, "mission": head.mission}

    return _guard(read)


def handle_get_declaration(cp: ControlPlane, constitution: str | None = None) -> dict:
    def read() -> dict:
        head = cp.current(constitution)
        return {"version": head.version, "declaration": head.declaration}

    return _guard(read)


def handle_get_principles(
    cp: ControlPlane, constitution: str | None = None, detail: str = TITLES
) -> dict:
    check_principles_detail(detail)

    def read() -> dict:
        head = cp.current(constitution)
        shape = COMPACT if detail == TITLES else FULL
        return {
            "version": head.version,
            "principles": [p.to_dict(shape) for p in head.principles],
        }

    return _guard(read)


def handle_get_principle(cp: ControlPlane, title: str, constitution: str | None = None) -> dict:
    def read() -> dict:
        head = cp.current(constitution)
        return {**head.principle(title).to_dict(), "version": head.version}

    return _guard(read)


def handle_set_direction(
    cp: ControlPlane,
    *,
    mission,
    principles,
    change_note,
    created_by,
    declaration=None,
    constitution: str | None = None,
    expected_version: int | None = None,
    authorized_by: str | None = None,
    token_id: int | None = None,
) -> dict:
    return _guard(
        lambda: cp.set_direction(
            mission=mission,
            declaration=declaration,
            principles=tuple(principles) if principles is not None else None,
            change_note=change_note,
            created_by=created_by,
            constitution=constitution,
            expected_version=expected_version,
            authorized_by=authorized_by,
            token_id=token_id,
        ).to_dict()
    )


def _request_token_id(server: Server, token_store) -> int | None:
    """The id of the token that authenticated the current request, or None.

    Called by the set_direction handler so the version records which
    credential wrote it. Resolved from the request's own Authorization
    header -- never from tool arguments, so a client cannot claim another
    token's identity. Returns None over stdio and in-process transports,
    where there is no bearer header, and None when no store was given.

    Returns the row id even for a token revoked mid-session: the endpoint
    already authenticated the request, and attribution should name the
    credential that was used."""
    if token_store is None:
        return None
    try:
        request = server.request_context.request
    except LookupError:
        return None
    if request is None:
        return None
    value = request.headers.get("authorization", "")
    if not value.startswith("Bearer "):
        return None
    token = token_store.token_by_hash(hash_value(value[len("Bearer ") :]))
    return token.id if token else None


def build_server(control_plane: ControlPlane, token_store=None) -> Server:
    server: Server = Server("kyno")
    subscribers: set = set()  # sessions subscribed to RESOURCE_URI
    pending: set = set()  # in-flight notification tasks, kept alive until done

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return TOOLS

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        match name:
            case "get_constitution":
                result = handle_get_constitution(
                    control_plane,
                    arguments.get("constitution"),
                    arguments.get("detail", COMPACT),
                )
            case "get_changes_since":
                _require(arguments, "known_version")
                result = handle_get_changes_since(
                    control_plane,
                    int(arguments["known_version"]),
                    arguments.get("constitution"),
                    arguments.get("detail", COMPACT),
                )
            case "get_mission":
                result = handle_get_mission(control_plane, arguments.get("constitution"))
            case "get_principles":
                result = handle_get_principles(
                    control_plane,
                    arguments.get("constitution"),
                    arguments.get("detail", TITLES),
                )
            case "get_declaration":
                result = handle_get_declaration(control_plane, arguments.get("constitution"))
            case "get_principle":
                _require(arguments, "title")
                result = handle_get_principle(
                    control_plane, arguments["title"], arguments.get("constitution")
                )
            case "export_versions":
                result = handle_export_versions(
                    control_plane,
                    arguments.get("constitution"),
                    from_version=arguments.get("from_version"),
                    to_version=arguments.get("to_version"),
                )
            case "set_direction":
                _require(arguments, "change_note")
                result = handle_set_direction(
                    control_plane,
                    mission=arguments.get("mission"),
                    declaration=arguments.get("declaration"),
                    principles=arguments.get("principles"),
                    change_note=arguments["change_note"],
                    created_by=arguments.get("created_by"),
                    constitution=arguments.get("constitution"),
                    expected_version=arguments.get("expected_version"),
                    authorized_by=arguments.get("authorized_by"),
                    token_id=_request_token_id(server, token_store),
                )
            case _:
                raise ValueError(f"unknown tool: {name}")
        return [types.TextContent(type="text", text=json.dumps(result))]

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
        return json.dumps(handle_get_constitution(control_plane))

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
    return server
