"""The /mcp gate: bearer values checked against the store's token table."""

import json
import logging
from datetime import UTC, datetime, timedelta

import pytest

from kyno.mcp_server import RESOURCE_URI, build_server
from kyno.service import ControlPlane
from kyno.store.sql import SqlConstitutionStore
from kyno.tokens import generate_value, hash_value
from kyno.transports import _tool_calls, token_for_request


def _token_store():
    store = SqlConstitutionStore(url="sqlite://")
    store.create_all()
    return store


def _mint(store, scope="write", name="t", expires_at=None):
    value = generate_value()
    store.add_token(name, scope, token_hash=hash_value(value), expires_at=expires_at)
    return value


def _now():
    return datetime.now(UTC)


def test_given_no_authorization_header_when_resolving_the_token_then_there_is_none():
    assert token_for_request({}, _token_store(), _now()) is None


def test_given_a_live_token_when_resolving_then_the_row_comes_back_with_its_scope():
    store = _token_store()
    value = _mint(store, scope="read", name="crew")

    token = token_for_request({"authorization": f"Bearer {value}"}, store, _now())

    assert token is not None
    assert (token.name, token.scope) == ("crew", "read")


def test_given_a_capitalized_authorization_header_when_resolving_then_it_still_matches():
    store = _token_store()
    value = _mint(store)
    assert token_for_request({"Authorization": f"Bearer {value}"}, store, _now()) is not None


def test_given_wrong_revoked_and_expired_tokens_when_resolving_then_all_answer_none():
    store = _token_store()
    revoked_value = _mint(store, name="revoked")
    store.revoke_token(store.tokens()[0].id)
    expired_value = _mint(store, name="expired", expires_at=_now() - timedelta(hours=1))

    for value in ("kyno_not-a-real-token", revoked_value, expired_value):
        assert token_for_request({"authorization": f"Bearer {value}"}, store, _now()) is None


def test_given_a_non_ascii_bearer_value_when_resolving_then_it_fails_closed_not_crashes():
    assert token_for_request({"authorization": "Bearer café"}, _token_store(), _now()) is None


def test_given_bodies_of_every_shape_when_listing_tool_calls_then_only_real_calls_count():
    assert _tool_calls(b"not json") == []
    assert _tool_calls(b'{"method": "initialize"}') == []
    assert _tool_calls(
        b'{"method": "tools/call", "params": {"name": "set_direction", "arguments": {}}}'
    ) == [("set_direction", "default")]
    assert _tool_calls(
        b'[{"method": "tools/call", "params": {"name": "get_constitution", '
        b'"arguments": {"constitution": "main"}}}]'
    ) == [("get_constitution", "main")]


@pytest.mark.asyncio
@pytest.mark.e2e
async def test_given_a_memory_session_when_calling_tools_end_to_end_then_the_mission_round_trips():
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


def _gated():
    """A store with one live write token, its control plane, and the app."""
    from kyno.transports import build_http_app

    store = _token_store()
    value = _mint(store)
    cp = ControlPlane(store)
    return store, value, build_http_app(cp, store=store)


def _bearer(value):
    return {**_MCP_HEADERS, "Authorization": f"Bearer {value}"}


def test_given_no_bearer_when_posting_to_the_http_app_then_it_is_401():
    from starlette.testclient import TestClient

    _store, _value, app = _gated()

    with TestClient(app) as client:
        response = client.post("/mcp", json=_initialize_payload(), headers=_MCP_HEADERS)

    assert response.status_code == 401


def test_given_every_dead_end_when_posting_then_the_answers_are_identical():
    # Unknown, revoked and expired must look the same from outside; a
    # distinct answer would confirm which tokens exist.
    from starlette.testclient import TestClient

    store, _value, app = _gated()
    revoked = _mint(store, name="revoked")
    store.revoke_token(next(t.id for t in store.tokens() if t.name == "revoked"))
    expired = _mint(store, name="expired", expires_at=_now() - timedelta(hours=1))

    answers = set()
    with TestClient(app) as client:
        for headers in (
            _MCP_HEADERS,
            _bearer("kyno_never-minted"),
            _bearer(revoked),
            _bearer(expired),
        ):
            response = client.post("/mcp", json=_initialize_payload(), headers=headers)
            answers.add((response.status_code, response.text))

    assert answers == {(401, "unauthorized")}


def test_given_an_authorized_request_when_the_lifespan_runs_then_it_reaches_the_mcp_handler():
    # Regression: without the lifespan, manager._task_group stays None and
    # every authorized request raises RuntimeError("Task group is not
    # initialized"), surfaced as a 500 by Starlette.
    from starlette.testclient import TestClient

    _store, value, app = _gated()

    with TestClient(app) as client:
        response = client.post("/mcp", json=_initialize_payload(), headers=_bearer(value))

    assert response.status_code != 500
    assert "Task group is not initialized" not in response.text
    assert response.status_code == 200
    assert '"serverInfo"' in response.text


def test_given_a_non_ascii_authorization_header_when_posting_then_it_is_401_not_500():
    from starlette.testclient import TestClient

    _store, _value, app = _gated()

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
    _store, _value, app = _gated()
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


def _drive_session(client, headers):
    init_resp = client.post("/mcp", json=_initialize_payload(), headers=headers)
    session_id = init_resp.headers["mcp-session-id"]
    h = {**headers, "mcp-session-id": session_id}
    client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=h)
    return h


def _call(client, headers, request_id, name, arguments):
    return client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
        headers=headers,
    )


def _sse_json(text):
    for line in text.splitlines():
        if line.startswith("data: "):
            return json.loads(line[len("data: ") :])
    raise AssertionError(f"no data: line in SSE body: {text!r}")


@pytest.mark.e2e
def test_given_a_write_token_when_driving_a_full_http_session_then_the_mission_round_trips():
    from starlette.testclient import TestClient

    _store, value, app = _gated()

    with TestClient(app) as client:
        h = _drive_session(client, _bearer(value))
        set_resp = _call(client, h, 2, "set_direction", {"mission": "M1", "change_note": "init"})
        assert set_resp.status_code == 200
        get_resp = _call(client, h, 3, "get_constitution", {})

    payload = json.loads(_sse_json(get_resp.text)["result"]["content"][0]["text"])
    assert payload["mission"] == "M1"
    assert payload["version"] == 1


def test_given_a_read_token_when_calling_set_direction_then_it_is_403_and_nothing_is_written():
    from starlette.testclient import TestClient

    store, _write_value, app = _gated()
    read_value = _mint(store, scope="read", name="crew")

    with TestClient(app) as client:
        h = _drive_session(client, _bearer(read_value))
        refused = _call(client, h, 2, "set_direction", {"mission": "M1", "change_note": "init"})
        allowed = _call(client, h, 3, "get_constitution", {})

    assert refused.status_code == 403
    assert "read-only" in refused.text
    assert allowed.status_code == 200
    assert store.head("default") is None


def test_given_authorized_requests_when_they_arrive_then_last_used_moves_once_per_window():
    from starlette.testclient import TestClient

    store, value, app = _gated()

    with TestClient(app) as client:
        client.post("/mcp", json=_initialize_payload(), headers=_bearer(value))
        first = store.tokens()[0].last_used_at
        client.post("/mcp", json=_initialize_payload(), headers=_bearer(value))
        second = store.tokens()[0].last_used_at

    assert first is not None
    # The second request lands inside the five-minute window, so the
    # stored value stays put.
    assert second == first


@pytest.mark.e2e
def test_given_a_tool_call_when_handled_then_the_request_log_carries_the_fields(caplog):
    from starlette.testclient import TestClient

    store, value, app = _gated()
    token_id = store.tokens()[0].id

    with caplog.at_level(logging.INFO, logger="kyno.requests"), TestClient(app) as client:
        h = _drive_session(client, _bearer(value))
        _call(client, h, 2, "get_constitution", {"constitution": "main"})

    line = next(r.getMessage() for r in caplog.records if "tool=get_constitution" in r.getMessage())
    assert f"token={token_id}" in line
    assert "name=t" in line
    assert "constitution=main" in line


def test_given_a_declared_body_over_the_cap_when_posting_then_it_is_413_before_the_body_is_read():
    from starlette.testclient import TestClient

    from kyno.transports import MAX_MCP_BODY_BYTES

    _store, value, app = _gated()

    with TestClient(app) as client:
        response = client.post(
            "/mcp", content=b"x" * (MAX_MCP_BODY_BYTES + 1), headers=_bearer(value)
        )

    assert response.status_code == 413


def test_given_a_declared_body_at_the_cap_when_posting_then_it_is_not_413():
    from starlette.testclient import TestClient

    from kyno.transports import MAX_MCP_BODY_BYTES

    _store, value, app = _gated()

    with TestClient(app) as client:
        response = client.post("/mcp", content=b"x" * MAX_MCP_BODY_BYTES, headers=_bearer(value))

    # Not valid JSON-RPC, so the MCP layer refuses it -- but as a bad
    # request, never as too large and never as a server error.
    assert response.status_code not in (413, 500)


def test_given_a_chunked_body_crossing_the_cap_when_streaming_then_it_is_413():
    # Chunked transfer declares no Content-Length, so only counting the
    # streamed bytes can enforce the cap.
    from starlette.testclient import TestClient

    from kyno.transports import MAX_MCP_BODY_BYTES

    _store, value, app = _gated()
    chunk = b"x" * (MAX_MCP_BODY_BYTES // 4 + 1)

    with TestClient(app) as client:
        response = client.post("/mcp", content=iter([chunk] * 5), headers=_bearer(value))

    assert "content-length" not in response.request.headers
    assert response.status_code == 413


def test_given_a_chunked_body_under_the_cap_when_streaming_then_it_reaches_the_mcp_handler():
    from starlette.testclient import TestClient

    _store, value, app = _gated()
    body = json.dumps(_initialize_payload()).encode()
    middle = len(body) // 2

    with TestClient(app) as client:
        response = client.post(
            "/mcp", content=iter([body[:middle], body[middle:]]), headers=_bearer(value)
        )

    assert response.status_code == 200
    assert '"serverInfo"' in response.text


def test_given_no_store_when_building_the_http_app_then_the_insecure_opt_in_is_required():
    # A library embedder opens the write endpoint as loudly as the CLI does.
    from kyno.errors import ConfigError
    from kyno.transports import build_http_app

    store = _token_store()
    with pytest.raises(ConfigError, match="token store"):
        build_http_app(ControlPlane(store))


def test_given_a_storeless_opt_in_app_when_posting_then_the_gate_is_off():
    from starlette.testclient import TestClient

    from kyno.transports import build_http_app

    store = _token_store()
    app = build_http_app(ControlPlane(store), allow_insecure=True)

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

    store = _token_store()
    value = _mint(store)
    with TestClient(build_http_app(ControlPlane(store), store=store)) as client:
        response = client.post("/mcp", json=_initialize_payload(), headers=_bearer(value))
    assert response.status_code == 200
