"""McpEndpoint: the token check, the size cap, the read/write rule, and
the hand-off to the MCP session manager -- unit tests and HTTP tests."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from kyno.mcp_endpoint import McpEndpoint, _tool_calls
from kyno.service import ControlPlane
from tests.mcp_requests import (
    MCP_HEADERS,
    bearer,
    call_tool,
    drive_session,
    initialize_payload,
    mint,
    sse_json,
    token_store,
)


def _endpoint(store):
    """An McpEndpoint around just the store; these tests never reach the
    MCP session manager, so none is needed."""
    return McpEndpoint(manager=None, token_store=store)


def test_given_a_request_with_no_authorization_header_when_resolving_then_no_token_is_found():
    assert _endpoint(token_store())._authenticate({}) is None


def test_given_a_live_token_when_resolving_then_the_row_comes_back_with_its_scope():
    store = token_store()
    value = mint(store, scope="read", name="crew")

    token = _endpoint(store)._authenticate({"authorization": f"Bearer {value}"})

    assert token is not None
    assert (token.name, token.scope) == ("crew", "read")


def test_given_a_capitalized_authorization_header_when_resolving_then_it_still_matches():
    store = token_store()
    value = mint(store)
    assert _endpoint(store)._authenticate({"Authorization": f"Bearer {value}"}) is not None


def test_given_a_token_that_is_unknown_revoked_or_expired_when_resolving_then_it_is_none():
    store = token_store()
    revoked_value = mint(store, name="revoked")
    store.revoke_token(store.tokens()[0].id)
    expired_value = mint(store, name="expired", expires_at=datetime.now(UTC) - timedelta(hours=1))

    for value in ("kyno_not-a-real-token", revoked_value, expired_value):
        assert _endpoint(store)._authenticate({"authorization": f"Bearer {value}"}) is None


def test_given_an_authorization_header_that_is_not_a_bearer_value_when_resolving_then_none():
    store = token_store()
    mint(store)
    assert _endpoint(store)._authenticate({"authorization": "Basic dXNlcjpwdw=="}) is None


def test_given_a_non_ascii_bearer_value_when_resolving_then_it_fails_closed_not_crashes():
    assert _endpoint(token_store())._authenticate({"authorization": "Bearer café"}) is None


def test_given_bodies_of_every_shape_when_listing_tool_calls_then_only_real_calls_count():
    assert _tool_calls(b"not json") == []
    assert _tool_calls(b'{"method": "initialize"}') == []
    assert _tool_calls(
        b'{"method": "tools/call", "params": {"name": "set_direction", "arguments": {}}}'
    ) == [("set_direction", "default")]
    # A batch (JSON array) is read by this check, one pair per item, in
    # order -- but the MCP SDK rejects arrays, so a batch never executes.
    # See the end-to-end test below.
    assert _tool_calls(
        b'[{"method": "tools/call", "params": {"name": "get_constitution", '
        b'"arguments": {"constitution": "main"}}},'
        b'{"method": "notifications/initialized"},'
        b'{"method": "tools/call", "params": {"name": "set_direction", '
        b'"arguments": {"mission": "M1"}}}]'
    ) == [("get_constitution", "main"), ("set_direction", "default")]


def _gated():
    """Build a store holding one live write token, and return it with that
    token's value and an app that checks bearer values against it."""
    from kyno.transports import build_http_app

    store = token_store()
    value = mint(store)
    cp = ControlPlane(store)
    return store, value, build_http_app(cp, token_store=store)


def test_given_no_bearer_when_posting_to_the_http_app_then_it_is_401():
    from starlette.testclient import TestClient

    _store, _value, app = _gated()

    with TestClient(app) as client:
        response = client.post("/mcp", json=initialize_payload(), headers=MCP_HEADERS)

    assert response.status_code == 401


def test_given_a_get_request_without_a_token_when_opening_the_stream_then_it_is_401():
    # The check runs before the method split, so GET and DELETE are gated
    # the same as POST. A GET opens the server-sent-events stream, where
    # the server pushes notifications; DELETE closes a session.
    from starlette.testclient import TestClient

    _store, _value, app = _gated()

    with TestClient(app) as client:
        response = client.get("/mcp", headers={"Accept": "text/event-stream"})

    assert response.status_code == 401


def test_given_every_dead_end_when_posting_then_the_answers_are_identical():
    # Unknown, revoked and expired must look the same from outside; a
    # distinct answer would confirm which tokens exist.
    from starlette.testclient import TestClient

    store, _value, app = _gated()
    revoked = mint(store, name="revoked")
    store.revoke_token(next(t.id for t in store.tokens() if t.name == "revoked"))
    expired = mint(store, name="expired", expires_at=datetime.now(UTC) - timedelta(hours=1))

    answers = set()
    with TestClient(app) as client:
        for headers in (
            MCP_HEADERS,
            bearer("kyno_never-minted"),
            bearer(revoked),
            bearer(expired),
        ):
            response = client.post("/mcp", json=initialize_payload(), headers=headers)
            answers.add((response.status_code, response.text))

    assert answers == {(401, "unauthorized")}


def test_given_an_authorized_request_when_the_lifespan_runs_then_it_reaches_the_mcp_handler():
    # Regression: without the lifespan, manager._task_group stays None and
    # every authorized request raises RuntimeError("Task group is not
    # initialized"), surfaced as a 500 by Starlette.
    from starlette.testclient import TestClient

    _store, value, app = _gated()

    with TestClient(app) as client:
        response = client.post("/mcp", json=initialize_payload(), headers=bearer(value))

    assert response.status_code != 500
    assert "Task group is not initialized" not in response.text
    assert response.status_code == 200
    assert '"serverInfo"' in response.text


def test_given_an_app_whose_lifespan_never_ran_when_posting_then_it_is_a_500():
    # The opposite of the test above, and the proof that it asserts
    # something real: without the `with` block the lifespan never runs, so
    # the MCP session manager is never started. The gate still passes the
    # request, and the unstarted manager fails it.
    from starlette.testclient import TestClient

    _store, value, app = _gated()
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post("/mcp", json=initialize_payload(), headers=bearer(value))

    assert response.status_code == 500


def test_given_a_non_ascii_authorization_header_when_posting_then_it_is_401_not_500():
    from starlette.testclient import TestClient

    _store, _value, app = _gated()

    with TestClient(app) as client:
        response = client.post(
            "/mcp",
            json=initialize_payload(),
            headers={**MCP_HEADERS, "Authorization": "Bearer sécret-héader".encode()},
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


@pytest.mark.e2e
def test_given_a_write_token_when_driving_an_http_session_then_the_written_mission_is_read_back():
    from starlette.testclient import TestClient

    _store, value, app = _gated()

    with TestClient(app) as client:
        h = drive_session(client, bearer(value))
        set_resp = call_tool(
            client, h, 2, "set_direction", {"mission": "M1", "change_note": "init"}
        )
        assert set_resp.status_code == 200
        get_resp = call_tool(client, h, 3, "get_constitution", {})

    payload = json.loads(sse_json(get_resp.text)["result"]["content"][0]["text"])
    assert payload["mission"] == "M1"
    assert payload["version"] == 1


def test_given_a_batched_body_when_posting_then_the_scope_check_reads_it_and_the_sdk_rejects_it():
    # Batches (JSON arrays) never execute. This test proves both layers:
    #
    # With a read token: our scope check reads every item in the array,
    # finds the set_direction, and answers 403 itself. The MCP SDK is
    # never reached.
    #
    # With a write token: our scope check allows the request, so it
    # reaches the MCP SDK -- and the SDK does not accept arrays, so it
    # answers 400 without executing anything.
    #
    # The 400 comes from the SDK, not from our code. If a future SDK
    # version starts accepting batches, that assertion fails, and we get
    # to decide whether to support batches instead of finding out after
    # they already run.
    from starlette.testclient import TestClient

    store, write_value, app = _gated()
    read_value = mint(store, scope="read", name="crew")
    batch = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "get_constitution", "arguments": {}},
        },
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "set_direction", "arguments": {"mission": "M1", "change_note": "x"}},
        },
    ]

    with TestClient(app) as client:
        refused = client.post("/mcp", json=batch, headers=bearer(read_value))
        rejected = client.post("/mcp", json=batch, headers=bearer(write_value))

    assert refused.status_code == 403
    assert rejected.status_code == 400
    assert store.head("default") is None


def test_given_a_read_token_when_calling_set_direction_then_it_is_403_and_nothing_is_written():
    from starlette.testclient import TestClient

    store, _write_value, app = _gated()
    read_value = mint(store, scope="read", name="crew")

    with TestClient(app) as client:
        h = drive_session(client, bearer(read_value))
        refused = call_tool(client, h, 2, "set_direction", {"mission": "M1", "change_note": "init"})
        allowed = call_tool(client, h, 3, "get_constitution", {})

    assert refused.status_code == 403
    assert "read-only" in refused.text
    assert allowed.status_code == 200
    assert store.head("default") is None


def test_given_a_declared_body_over_the_cap_when_posting_then_it_is_413_before_the_body_is_read():
    from starlette.testclient import TestClient

    from kyno.transports import MAX_MCP_BODY_BYTES

    _store, value, app = _gated()

    with TestClient(app) as client:
        response = client.post(
            "/mcp", content=b"x" * (MAX_MCP_BODY_BYTES + 1), headers=bearer(value)
        )

    assert response.status_code == 413


def test_given_a_declared_body_at_the_cap_when_posting_then_it_is_not_413():
    from starlette.testclient import TestClient

    from kyno.transports import MAX_MCP_BODY_BYTES

    _store, value, app = _gated()

    with TestClient(app) as client:
        response = client.post("/mcp", content=b"x" * MAX_MCP_BODY_BYTES, headers=bearer(value))

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
        response = client.post("/mcp", content=iter([chunk] * 5), headers=bearer(value))

    assert "content-length" not in response.request.headers
    assert response.status_code == 413


def test_given_a_chunked_body_under_the_cap_when_streaming_then_it_reaches_the_mcp_handler():
    from starlette.testclient import TestClient

    _store, value, app = _gated()
    body = json.dumps(initialize_payload()).encode()
    middle = len(body) // 2

    with TestClient(app) as client:
        response = client.post(
            "/mcp", content=iter([body[:middle], body[middle:]]), headers=bearer(value)
        )

    assert response.status_code == 200
    assert '"serverInfo"' in response.text
