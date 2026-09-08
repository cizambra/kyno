"""The in-process MCP client journey through the built server."""

import json

import pytest

from kyno.mcp_server import RESOURCE_URI, build_server
from kyno.service import ControlPlane
from kyno.store.sql import SqlConstitutionStore


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_given_an_in_process_session_when_calling_tools_then_the_written_mission_reads_back():
    from mcp.shared.memory import create_connected_server_and_client_session

    store = SqlConstitutionStore(url="sqlite://")
    store.create_all()
    cp = ControlPlane(store)
    server = build_server(cp)

    async with create_connected_server_and_client_session(server) as client:
        await client.call_tool(
            "set_direction", {"mission": "M1", "principles": ["p1"], "change_note": "init"}
        )
        res = await client.call_tool("get_constitution", {})
        payload = json.loads(res.content[0].text)
        assert payload["mission"] == "M1" and payload["version"] == 1

        read = await client.read_resource(RESOURCE_URI)
        assert "M1" in read.contents[0].text

    assert store.head("default").token_id is None
