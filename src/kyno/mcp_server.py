"""Compose Kyno's MCP tool and resource interfaces."""

from mcp.server import Server

from kyno.mcp_resource_handlers import register_resources
from kyno.mcp_tool_handlers import register_tools
from kyno.service import ControlPlane


def build_server(control_plane: ControlPlane, token_store=None) -> Server:
    server = Server("kyno")
    register_tools(server, control_plane, token_store)
    register_resources(server, control_plane, token_store)
    return server
