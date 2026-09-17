"""MCP tool registration and dispatch."""

import json

import mcp.types as types
from mcp.server import Server

from kyno.mcp.handlers import (
    _delivery_query,
    _require,
    handle_export_versions,
    handle_get_changes_since,
    handle_get_constitution,
    handle_get_declaration,
    handle_get_mission,
    handle_get_principle,
    handle_get_principles,
    handle_set_direction,
    handle_whoami,
)
from kyno.mcp.request_context import _request_token, record_response
from kyno.mcp.tools import DIRECTION_READS, TITLES, TOOLS
from kyno.service import ControlPlane
from kyno.wire.delivery_context import delivery_context
from kyno.wire.models import DetailLevel


def register_tools(server: Server, control_plane: ControlPlane, token_store=None) -> None:
    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return TOOLS

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        if name in DIRECTION_READS:
            delivery_context(arguments)
        match name:
            case "get_delivery_record":
                _require(arguments, "record_id")
                result = _delivery_query(
                    control_plane, lambda store: store.get(arguments["record_id"])
                )
            case "get_constitution":
                result = handle_get_constitution(
                    control_plane,
                    arguments.get("constitution"),
                    arguments.get("detail", DetailLevel.COMPACT),
                    version=arguments.get("version"),
                )
            case "get_changes_since":
                _require(arguments, "known_version")
                result = handle_get_changes_since(
                    control_plane,
                    int(arguments["known_version"]),
                    arguments.get("constitution"),
                    arguments.get("detail", DetailLevel.COMPACT),
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
                requester = _request_token(server, token_store)
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
                    token_id=requester.id if requester else None,
                )
            case "whoami":
                result = handle_whoami(_request_token(server, token_store))
            case "list_delivery_records":
                result = _delivery_query(
                    control_plane,
                    lambda store: store.list(
                        **{
                            key: arguments[key]
                            for key in (
                                "correlation_id",
                                "constitution",
                                "since",
                                "until",
                                "after",
                                "limit",
                            )
                            if key in arguments
                        }
                    ),
                )
            case _:
                raise ValueError(f"unknown tool: {name}")
        if name in DIRECTION_READS:
            record_response(server, control_plane, token_store, result, name, arguments)
        return [types.TextContent(type="text", text=json.dumps(result))]
