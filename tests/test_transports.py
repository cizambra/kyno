"""build_http_app: the app assembly, and serving across MCP releases."""

import json

import pytest

from kyno.mcp_server import RESOURCE_URI, build_server
from kyno.service import ControlPlane
from kyno.store.sql import SqlConstitutionStore
from tests.mcp_requests import MCP_HEADERS, bearer, initialize_payload, mint, token_store


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_given_a_memory_session_when_calling_tools_then_the_set_mission_is_read_back():
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


def test_given_no_token_store_when_building_the_http_app_then_allow_insecure_is_required():
    # An embedder has to opt in explicitly, the same as the CLI does.
    from kyno.errors import ConfigError
    from kyno.transports import build_http_app

    store = token_store()
    with pytest.raises(ConfigError, match="token store"):
        build_http_app(ControlPlane(store))


def test_given_no_token_store_and_allow_insecure_when_posting_then_no_token_is_checked():
    from starlette.testclient import TestClient

    from kyno.transports import build_http_app

    store = token_store()
    app = build_http_app(ControlPlane(store), allow_insecure=True)

    with TestClient(app) as client:
        response = client.post("/mcp", json=initialize_payload(), headers=MCP_HEADERS)

    assert response.status_code != 500
    assert "Task group is not initialized" not in response.text
    assert response.status_code == 200
    assert '"serverInfo"' in response.text


def test_given_an_mcp_release_without_the_body_cap_when_building_the_app_then_it_still_serves(
    monkeypatch,
):
    """Old mcp releases have no max_request_body_size; the app falls back to
    building the manager without it instead of failing to start."""
    import mcp.server.streamable_http_manager as manager_module

    from kyno.transports import build_http_app

    real = manager_module.StreamableHTTPSessionManager

    class OldRelease:
        def __new__(cls, app=None, **kwargs):
            if "max_request_body_size" in kwargs:
                raise TypeError("unexpected keyword argument")
            return real(app=app)

    monkeypatch.setattr(manager_module, "StreamableHTTPSessionManager", OldRelease)
    from starlette.testclient import TestClient

    store = token_store()
    value = mint(store)
    with TestClient(build_http_app(ControlPlane(store), token_store=store)) as client:
        response = client.post("/mcp", json=initialize_payload(), headers=bearer(value))
    assert response.status_code == 200
