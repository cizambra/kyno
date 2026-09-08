"""HTTP app assembly and compatibility across MCP releases."""

import pytest

from kyno.service import ControlPlane
from tests.mcp_requests import MCP_HEADERS, bearer, initialize_payload, mint, token_store


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
