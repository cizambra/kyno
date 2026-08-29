from kyno.transports import resolve_scope


def test_given_no_tokens_configured_when_resolving_scope_then_the_door_is_open():
    # No auth configured: every request is a write, as before.
    assert resolve_scope({}, None) == "write"


def test_given_the_write_token_when_resolving_scope_then_it_is_write():
    assert resolve_scope({"authorization": "Bearer secret"}, "secret") == "write"
    assert resolve_scope({"authorization": "Bearer wrong"}, "secret") is None
    assert resolve_scope({}, "secret") is None


def test_given_a_read_token_when_resolving_scope_then_it_is_read():
    assert resolve_scope({"authorization": "Bearer r1"}, "w", ("r1", "r2")) == "read"
    assert resolve_scope({"authorization": "Bearer r2"}, "w", ("r1", "r2")) == "read"
    assert resolve_scope({"authorization": "Bearer w"}, "w", ("r1",)) == "write"
    assert resolve_scope({"authorization": "Bearer nope"}, "w", ("r1",)) is None


def test_given_only_read_tokens_when_a_wrong_bearer_arrives_then_the_door_stays_shut():
    # Only read tokens configured: nothing resolves to write.
    assert resolve_scope({"authorization": "Bearer r1"}, None, ("r1",)) == "read"
    assert resolve_scope({}, None, ("r1",)) is None


def test_header_lookup_is_case_insensitive():
    assert resolve_scope({"Authorization": "Bearer secret"}, "secret") == "write"


def test_non_ascii_bearer_value_is_rejected_not_crashed():
    # hmac.compare_digest raises TypeError comparing a non-ASCII str against
    # an ASCII str; that must fail closed (401), not surface as a 500.
    assert resolve_scope({"authorization": "Bearer café"}, "tok") is None


import pytest

from kyno.mcp_server import RESOURCE_URI, build_server
from kyno.service import ControlPlane
from kyno.store.sql import SqlConstitutionStore


@pytest.mark.asyncio
async def test_end_to_end_tool_calls_over_memory_session():
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


def test_http_app_rejects_unauthorized_request():
    from starlette.testclient import TestClient

    from kyno.transports import build_http_app

    app = build_http_app(_make_control_plane(), token="secret")

    with TestClient(app) as client:
        response = client.post("/mcp", json=_initialize_payload(), headers=_MCP_HEADERS)

    assert response.status_code == 401


def test_http_app_lifespan_is_wired_so_authorized_requests_reach_the_mcp_handler():
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


def test_http_app_non_ascii_authorization_header_is_401_not_500():
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
async def test_http_handle_non_utf8_header_bytes_is_401_not_500():
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


def test_http_end_to_end_tool_call_round_trips_mission():
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


def test_a_declared_body_over_the_cap_is_413_before_the_body_is_read():
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


def test_a_declared_body_at_the_cap_is_not_413():
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


def test_a_chunked_body_crossing_the_cap_mid_stream_is_413():
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


def test_a_chunked_body_under_the_cap_still_reaches_the_mcp_handler():
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


def test_a_tokenless_app_requires_the_insecure_opt_in():
    # A library embedder opens the write endpoint as loudly as the CLI does.
    from kyno.errors import ConfigError
    from kyno.transports import build_http_app

    with pytest.raises(ConfigError, match="token"):
        build_http_app(_make_control_plane(), token=None)


def test_http_app_lifespan_is_wired_when_no_token_configured():
    from starlette.testclient import TestClient

    from kyno.transports import build_http_app

    app = build_http_app(_make_control_plane(), token=None, allow_insecure=True)

    with TestClient(app) as client:
        response = client.post("/mcp", json=_initialize_payload(), headers=_MCP_HEADERS)

    assert response.status_code != 500
    assert "Task group is not initialized" not in response.text
    assert response.status_code == 200
    assert '"serverInfo"' in response.text


@pytest.mark.asyncio
async def test_given_a_read_only_server_when_listing_and_calling_then_set_direction_is_gone():
    from mcp.shared.memory import create_connected_server_and_client_session

    server = build_server(_make_control_plane(), read_only=True)
    async with create_connected_server_and_client_session(server) as client:
        listed = await client.list_tools()
        names = {tool.name for tool in listed.tools}
        assert "set_direction" not in names
        assert "get_constitution" in names

        result = await client.call_tool("set_direction", {"change_note": "n", "mission": "M"})
        assert result.isError
        assert "read-only" in result.content[0].text


def test_given_a_read_token_when_posting_to_the_http_app_then_the_read_only_server_answers():
    from starlette.testclient import TestClient

    from kyno.transports import build_http_app

    app = build_http_app(_make_control_plane(), token="w", read_tokens=("r",))
    with TestClient(app) as client:
        ok = client.post(
            "/mcp",
            json=_initialize_payload(),
            headers={**_MCP_HEADERS, "Authorization": "Bearer r"},
        )
        assert ok.status_code == 200
        bad = client.post("/mcp", json=_initialize_payload(), headers=_MCP_HEADERS)
        assert bad.status_code == 401


def test_given_a_read_token_equal_to_the_write_token_when_building_the_app_then_it_is_refused():
    import pytest

    from kyno.errors import ConfigError
    from kyno.transports import build_http_app

    with pytest.raises(ConfigError, match="one scope"):
        build_http_app(_make_control_plane(), token="same", read_tokens=("same",))
