"""The MCP tool surface: every tool declared next to the scope a token
needs to call it, and the two projections the rest of the server reads.
The server lists TOOLS; the endpoint checks TOOL_SCOPES."""

from __future__ import annotations

import mcp.types as types

from kyno.models import DETAIL_LEVELS, FULL, READ, WRITE

# get_principles has its own detail vocabulary: "titles" names exactly what
# the small answer contains, where "compact" only means something when the
# payload is the whole document.
TITLES = "titles"
PRINCIPLES_DETAIL_LEVELS = (TITLES, FULL)


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

# The same wording on every read whose result can be combined with another.
_DRIFT = "If the version disagrees with one you already hold, the direction moved: re-read it."

# Each entry declares one tool together with the scope a token needs to
# call it, so a tool cannot exist without stating what it needs. TOOLS
# and TOOL_SCOPES below are projections of this list and nothing else.
DECLARATIONS = [
    (
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
        READ,
    ),
    (
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
        READ,
    ),
    (
        types.Tool(
            name="get_mission",
            description=(
                "Return the mission alone, with the version it belongs to. One piece "
                f"of the constitution, for when a compact read is all you need. {_DRIFT}"
            ),
            inputSchema={"type": "object", "properties": {"constitution": _CONSTITUTION_ARG}},
        ),
        READ,
    ),
    (
        types.Tool(
            name="get_declaration",
            description=(
                "Return the long-form declaration alone, with the version it belongs "
                f"to. One piece of the constitution, for when a compact read left it out. {_DRIFT}"
            ),
            inputSchema={"type": "object", "properties": {"constitution": _CONSTITUTION_ARG}},
        ),
        READ,
    ),
    (
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
        READ,
    ),
    (
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
                    "title": {
                        "type": "string",
                        "description": "Exact title, from get_constitution.",
                    },
                    "constitution": _CONSTITUTION_ARG,
                },
                "required": ["title"],
            },
        ),
        READ,
    ),
    (
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
        READ,
    ),
    (
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
        WRITE,
    ),
    (
        types.Tool(
            name="whoami",
            description=(
                "Return the id, name and scope of the token this request "
                "authenticated with. Every field is null when the server did not "
                "check a token (stdio, or a server running with allow_insecure)."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
        READ,
    ),
]

TOOLS = [tool for tool, _ in DECLARATIONS]
TOOL_SCOPES = {tool.name: scope for tool, scope in DECLARATIONS}
