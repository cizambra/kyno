from __future__ import annotations

import asyncio
import json

import mcp.types as types
from mcp.server import Server
from pydantic import AnyUrl

from kyno.errors import CoherenceError
from kyno.models import COMPACT, DETAIL_LEVELS, FULL, check_detail
from kyno.sdk.client import RESOURCE_URI as RESOURCE_URI  # the SDK owns the wire name
from kyno.service import ControlPlane

# get_principles has its own detail vocabulary: "titles" names exactly what
# the small answer contains, where "compact" only means something when the
# payload is the whole document.
TITLES = "titles"
PRINCIPLES_DETAIL_LEVELS = (TITLES, FULL)


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


# Reads default to compact. The declaration and the descriptions are the
# long text, and an agent that pulls before every step pays for them each
# time; asking for them is one argument away.
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


# The targeted reads: having pulled the handles, buy the piece that turned
# out to matter rather than the whole document again. Every one of them
# answers with the version it came from, which is what makes mixing them
# safe -- two answers on one version describe one document.
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
        ).to_dict()
    )


_PRINCIPLES_DETAIL_ARG = {
    "type": "string",
    "enum": list(PRINCIPLES_DETAIL_LEVELS),
    "description": (
        'How much of each principle to return. "titles" (the default) is the '
        'handles alone; "full" adds the description under each one.'
    ),
}

_DETAIL_ARG = {
    "type": "string",
    "enum": list(DETAIL_LEVELS),
    "description": (
        'How much to return. "compact" (the default) is the mission and the '
        'principle titles; "full" adds the declaration and each principle\'s '
        "description."
    ),
}

# An omitted `constitution` is passed on as None rather than "default", so a
# control plane pinned to another name keeps serving that one.
_CONSTITUTION_ARG = {
    "type": "string",
    "description": 'Which named constitution to act on. Defaults to "default".',
}

# Either shape a principle comes in: a bare title, or a title with the
# paragraph that disambiguates it.
_PRINCIPLE_ITEM = {
    "anyOf": [
        {"type": "string"},
        {
            "type": "object",
            "properties": {"title": {"type": "string"}, "description": {"type": "string"}},
            "required": ["title"],
        },
    ]
}

# Said once, in the same words, on every read that can be mixed with another.
_DRIFT = "If the version disagrees with one you already hold, the direction moved: re-read it."

_TOOLS = [
    types.Tool(
        name="get_constitution",
        description=(
            "Return the constitution in force now. Compact by default: pass "
            "detail='full' to include the declaration and the principle descriptions."
        ),
        inputSchema={
            "type": "object",
            "properties": {"constitution": _CONSTITUTION_ARG, "detail": _DETAIL_ARG},
        },
    ),
    types.Tool(
        name="get_changes_since",
        description=(
            "Return the current direction and what changed since a known version. "
            "Compact by default: pass detail='full' to include the declaration "
            "and the principle descriptions."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "known_version": {"type": "integer"},
                "constitution": _CONSTITUTION_ARG,
                "detail": _DETAIL_ARG,
            },
            "required": ["known_version"],
        },
    ),
    types.Tool(
        name="get_mission",
        description=(
            "Return the mission alone, with the version it belongs to. One piece "
            f"of the constitution, for when a compact read is all you need. {_DRIFT}"
        ),
        inputSchema={"type": "object", "properties": {"constitution": _CONSTITUTION_ARG}},
    ),
    types.Tool(
        name="get_declaration",
        description=(
            "Return the long-form declaration alone, with the version it belongs "
            f"to. One piece of the constitution, for when a compact read left it out. {_DRIFT}"
        ),
        inputSchema={"type": "object", "properties": {"constitution": _CONSTITUTION_ARG}},
    ),
    types.Tool(
        name="get_principles",
        description=(
            "Return every principle, with the version they belong to. Titles alone "
            "by default: pass detail='full' to include the description under each "
            f"one, which is what adjudicating between them takes. {_DRIFT}"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "constitution": _CONSTITUTION_ARG,
                "detail": _PRINCIPLES_DETAIL_ARG,
            },
        },
    ),
    types.Tool(
        name="get_principle",
        description=(
            "Return one principle's title and description, with the version it "
            "belongs to. Titles come from get_constitution or get_principles and "
            f"must match exactly. {_DRIFT}"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Exact title, from get_constitution."},
                "constitution": _CONSTITUTION_ARG,
            },
            "required": ["title"],
        },
    ),
    types.Tool(
        name="export_versions",
        description=(
            "Return the full version history, ascending: every version's "
            "content and its edit metadata. Bounds are inclusive; omitted means all."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "constitution": _CONSTITUTION_ARG,
                "from_version": {"type": ["integer", "null"]},
                "to_version": {"type": ["integer", "null"]},
            },
        },
    ),
    types.Tool(
        name="set_direction",
        description=(
            "Append a new constitution version, with a mission, a declaration "
            "and/or principles. Omitted fields carry forward from the current "
            'version; "" clears one.'
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "mission": {"type": ["string", "null"]},
                "declaration": {"type": ["string", "null"]},
                "principles": {"type": ["array", "null"], "items": _PRINCIPLE_ITEM},
                "change_note": {"type": "string"},
                "created_by": {"type": ["string", "null"]},
                "constitution": _CONSTITUTION_ARG,
                "expected_version": {"type": ["integer", "null"]},
                "authorized_by": {
                    "type": ["string", "null"],
                    "enum": ["operator", "automation", "override", None],
                },
            },
            "required": ["change_note"],
        },
    ),
]


def build_server(control_plane: ControlPlane) -> Server:
    server: Server = Server("kyno")
    subscribers: set = set()  # sessions subscribed to RESOURCE_URI
    pending: set = set()  # in-flight notification tasks, kept alive until done

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return _TOOLS

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

    # One URI cannot stand for several constitutions, so the resource is the
    # control plane's default one, served compact (a resource takes no
    # parameters). Any constitution's version bump notifies here; agents read
    # by name with the tools, and a redundant self-describing pull is cheap.
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
