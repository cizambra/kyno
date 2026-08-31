from kyno.transports import require_token


def test_given_no_token_configured_when_a_request_arrives_then_it_is_allowed():
    assert require_token({}, None) is True


def test_given_a_configured_token_when_a_request_arrives_then_only_the_matching_bearer_passes():
    assert require_token({"authorization": "Bearer secret"}, "secret") is True
    assert require_token({"authorization": "Bearer wrong"}, "secret") is False
    assert require_token({}, "secret") is False


def test_given_a_capitalized_authorization_header_when_checking_the_token_then_it_still_matches():
    assert require_token({"Authorization": "Bearer secret"}, "secret") is True


def test_given_a_non_ascii_bearer_value_when_checking_the_token_then_it_fails_closed_not_crashes():
    # hmac.compare_digest raises TypeError comparing a non-ASCII str against
    # an ASCII str; that must fail closed (401), not surface as a 500.
    assert require_token({"authorization": "Bearer café"}, "tok") is False


import pytest

from kyno.mcp_server import RESOURCE_URI, build_server
from kyno.service import ControlPlane
from kyno.store.sql import SqlConstitutionStore


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_given_a_memory_session_when_calling_tools_end_to_end_then_the_mission_round_trips():
    from mcp.shared.memory import create_connected_server_and_client_session

    store = SqlConstitutionStore(url="sqlite://")
    store.create_all()
    cp = ControlPlane(store)
    server = build_server(cp)

    async with create_connected_server_and_client_session(server) as client:
        import json

        await client.call_tool(
            "set_direction", {"mission": "M1", "principles": ["p1"], "change_note": "init"}
        )
        res = await client.call_tool("get_constitution", {})
        payload = json.loads(res.content[0].text)
        assert payload["mission"] == "M1" and payload["version"] == 1

        read = await client.read_resource(RESOURCE_URI)
        assert "M1" in read.contents[0].text


def _make_control_plane():
    store = SqlConstitutionStore(url="sqlite://")
    store.create_all()
    return ControlPlane(store)


def _initialize_payload():
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "0.0"},
        },
    }


_MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


def test_given_no_bearer_when_posting_to_the_http_app_then_it_is_401():
    from starlette.testclient import TestClient

    from kyno.transports import build_http_app

    app = build_http_app(_make_control_plane(), token="secret")

    with TestClient(app) as client:
        response = client.post("/mcp", json=_initialize_payload(), headers=_MCP_HEADERS)

    assert response.status_code == 401


def test_given_an_authorized_request_when_the_lifespan_runs_then_it_reaches_the_mcp_handler():
    # Regression: without the lifespan, manager._task_group stays None and
    # every authorized request raises RuntimeError("Task group is not
    # initialized"), surfaced as a 500 by Starlette.
    from starlette.testclient import TestClient

    from kyno.transports import build_http_app

    app = build_http_app(_make_control_plane(), token="secret")

    with TestClient(app) as client:
        response = client.post(
            "/mcp",
            json=_initialize_payload(),
            headers={**_MCP_HEADERS, "Authorization": "Bearer secret"},
        )

    assert response.status_code != 500
    assert "Task group is not initialized" not in response.text
    assert response.status_code == 200
    assert '"serverInfo"' in response.text


def test_given_a_non_ascii_authorization_header_when_posting_then_it_is_401_not_500():
    from starlette.testclient import TestClient

    from kyno.transports import build_http_app

    app = build_http_app(_make_control_plane(), token="secret")

    with TestClient(app) as client:
        response = client.post(
            "/mcp",
            json=_initialize_payload(),
            headers={**_MCP_HEADERS, "Authorization": "Bearer sécret-héader".encode()},
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_given_non_utf8_header_bytes_when_handling_the_request_then_it_is_401_not_500():
    # A header value that isn't valid UTF-8 at all (not just non-ASCII) must
    # not crash v.decode() in handle(); it should fail closed as 401.
    from kyno.transports import build_http_app

    app = build_http_app(_make_control_plane(), token="secret")
    # Found by path, not by position: the app also carries the public
    # constitution routes, and their order is not this test's business.
    handle = next(r for r in app.routes if getattr(r, "path", None) == "/mcp").app

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": [(b"authorization", b"Bearer \xff\xfe-not-utf8")],
    }

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    sent = []

    async def send(message):
        sent.append(message)

    await handle(scope, receive, send)
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    assert status == 401


@pytest.mark.e2e
def test_given_the_bearer_gate_when_driving_a_full_http_session_then_the_mission_round_trips():
    # Existing HTTP tests stop at initialize; this drives a full session
    # (set_direction then get_constitution) through the real bearer-token gate.
    import json

    from starlette.testclient import TestClient

    from kyno.transports import build_http_app

    app = build_http_app(_make_control_plane(), token="secret")
    headers = {**_MCP_HEADERS, "Authorization": "Bearer secret"}

    with TestClient(app) as client:
        init_resp = client.post("/mcp", json=_initialize_payload(), headers=headers)
        session_id = init_resp.headers["mcp-session-id"]
        h = {**headers, "mcp-session-id": session_id}
        client.post(
            "/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=h
        )

        set_resp = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "set_direction",
                    "arguments": {"mission": "M1", "change_note": "init"},
                },
            },
            headers=h,
        )
        assert set_resp.status_code == 200

        get_resp = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "get_constitution", "arguments": {}},
            },
            headers=h,
        )

    def sse_json(text):
        for line in text.splitlines():
            if line.startswith("data: "):
                return json.loads(line[len("data: ") :])
        raise AssertionError(f"no data: line in SSE body: {text!r}")

    payload = json.loads(sse_json(get_resp.text)["result"]["content"][0]["text"])
    assert payload["mission"] == "M1"
    assert payload["version"] == 1


def test_given_a_declared_body_over_the_cap_when_posting_then_it_is_413_before_the_body_is_read():
    from starlette.testclient import TestClient

    from kyno.transports import MAX_MCP_BODY_BYTES, build_http_app

    app = build_http_app(_make_control_plane(), token="secret")

    with TestClient(app) as client:
        response = client.post(
            "/mcp",
            content=b"x" * (MAX_MCP_BODY_BYTES + 1),
            headers={**_MCP_HEADERS, "Authorization": "Bearer secret"},
        )

    assert response.status_code == 413


def test_given_a_declared_body_at_the_cap_when_posting_then_it_is_not_413():
    from starlette.testclient import TestClient

    from kyno.transports import MAX_MCP_BODY_BYTES, build_http_app

    app = build_http_app(_make_control_plane(), token="secret")

    with TestClient(app) as client:
        response = client.post(
            "/mcp",
            content=b"x" * MAX_MCP_BODY_BYTES,
            headers={**_MCP_HEADERS, "Authorization": "Bearer secret"},
        )

    # Not valid JSON-RPC, so the MCP layer refuses it -- but as a bad
    # request, never as too large and never as a server error.
    assert response.status_code not in (413, 500)


def test_given_a_chunked_body_crossing_the_cap_when_streaming_then_it_is_413():
    # Chunked transfer declares no Content-Length, so only counting the
    # streamed bytes can enforce the cap.
    from starlette.testclient import TestClient

    from kyno.transports import MAX_MCP_BODY_BYTES, build_http_app

    app = build_http_app(_make_control_plane(), token="secret")
    chunk = b"x" * (MAX_MCP_BODY_BYTES // 4 + 1)

    with TestClient(app) as client:
        response = client.post(
            "/mcp",
            content=iter([chunk] * 5),
            headers={**_MCP_HEADERS, "Authorization": "Bearer secret"},
        )

    assert "content-length" not in response.request.headers
    assert response.status_code == 413


def test_given_a_chunked_body_under_the_cap_when_streaming_then_it_reaches_the_mcp_handler():
    import json

    from starlette.testclient import TestClient

    from kyno.transports import build_http_app

    app = build_http_app(_make_control_plane(), token="secret")
    body = json.dumps(_initialize_payload()).encode()
    middle = len(body) // 2

    with TestClient(app) as client:
        response = client.post(
            "/mcp",
            content=iter([body[:middle], body[middle:]]),
            headers={**_MCP_HEADERS, "Authorization": "Bearer secret"},
        )

    assert response.status_code == 200
    assert '"serverInfo"' in response.text


def test_given_no_token_when_building_the_http_app_then_the_insecure_opt_in_is_required():
    # A library embedder opens the write endpoint as loudly as the CLI does.
    from kyno.errors import ConfigError
    from kyno.transports import build_http_app

    with pytest.raises(ConfigError, match="token"):
        build_http_app(_make_control_plane(), token=None)


def test_given_a_tokenless_opt_in_app_when_posting_then_the_lifespan_still_reaches_the_handler():
    from starlette.testclient import TestClient

    from kyno.transports import build_http_app

    app = build_http_app(_make_control_plane(), token=None, allow_insecure=True)

    with TestClient(app) as client:
        response = client.post("/mcp", json=_initialize_payload(), headers=_MCP_HEADERS)

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

    with TestClient(build_http_app(_make_control_plane(), token="secret")) as client:
        response = client.post(
            "/mcp",
            json=_initialize_payload(),
            headers={**_MCP_HEADERS, "Authorization": "Bearer secret"},
        )
    assert response.status_code == 200
