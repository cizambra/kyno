"""HTTP app authentication, lifespan, and body-limit contracts."""

import json
from datetime import UTC, datetime, timedelta

from kyno.service import ControlPlane
from tests.mcp_requests import (
    MCP_HEADERS,
    bearer,
    call_tool,
    drive_session,
    gated_http_app,
    initialize_payload,
    mint,
    sse_json,
    token_store,
)


def test_given_no_bearer_when_posting_to_the_http_app_then_it_is_401():
    from starlette.testclient import TestClient

    _store, _value, app = gated_http_app()

    with TestClient(app) as client:
        response = client.post("/mcp", json=initialize_payload(), headers=MCP_HEADERS)

    assert response.status_code == 401


def test_given_a_get_request_without_a_token_when_opening_the_stream_then_it_is_401():
    # The check runs before the method split, so GET and DELETE are gated
    # the same as POST. A GET opens the server-sent-events stream, where
    # the server pushes notifications; DELETE closes a session.
    from starlette.testclient import TestClient

    _store, _value, app = gated_http_app()

    with TestClient(app) as client:
        response = client.get("/mcp", headers={"Accept": "text/event-stream"})

    assert response.status_code == 401


def test_given_every_dead_end_when_posting_then_the_answers_are_identical():
    # Unknown, revoked and expired must look the same from outside; a
    # distinct answer would confirm which tokens exist.
    from starlette.testclient import TestClient

    store, _value, app = gated_http_app()
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

    _store, value, app = gated_http_app()

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

    _store, value, app = gated_http_app()
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post("/mcp", json=initialize_payload(), headers=bearer(value))

    assert response.status_code == 500


def test_given_a_non_ascii_authorization_header_when_posting_then_it_is_401_not_500():
    from starlette.testclient import TestClient

    _store, _value, app = gated_http_app()

    with TestClient(app) as client:
        response = client.post(
            "/mcp",
            json=initialize_payload(),
            headers={**MCP_HEADERS, "Authorization": "Bearer sécret-héader".encode()},
        )

    assert response.status_code == 401


def test_given_a_write_token_when_calling_an_undeclared_tool_then_it_is_403_as_unknown():
    # Fail closed: a tool nobody declared a scope for is denied even for
    # the strongest scope there is. The refusal names the tool as unknown
    # rather than blaming the token.
    from starlette.testclient import TestClient

    store, write_value, app = gated_http_app()

    with TestClient(app) as client:
        h = drive_session(client, bearer(write_value))
        response = call_tool(client, h, 2, "not_a_declared_tool", {})

    assert response.status_code == 403
    assert "unknown tool: 'not_a_declared_tool' does not exist" in response.text
    assert store.head("default") is None


def test_given_a_read_token_when_calling_an_undeclared_tool_then_it_is_403_as_unknown():
    from starlette.testclient import TestClient

    store, _, app = gated_http_app()
    read_value = mint(store, scope="read", name="crew")

    with TestClient(app) as client:
        h = drive_session(client, bearer(read_value))
        response = call_tool(client, h, 2, "not_a_declared_tool", {})

    assert response.status_code == 403
    assert "unknown tool: 'not_a_declared_tool' does not exist" in response.text


def test_given_a_read_token_when_calling_a_read_tool_then_it_answers():
    # The scope check must not get in the way of what a read token is for.
    from starlette.testclient import TestClient

    store, _, app = gated_http_app()
    read_value = mint(store, scope="read", name="crew")

    with TestClient(app) as client:
        h = drive_session(client, bearer(read_value))
        response = call_tool(client, h, 2, "get_mission", {})

    assert response.status_code == 200
    payload = json.loads(sse_json(response.text)["result"]["content"][0]["text"])
    assert payload == {"version": 0, "mission": ""}


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

    store, write_value, app = gated_http_app()
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

    store, _write_value, app = gated_http_app()
    read_value = mint(store, scope="read", name="crew")

    with TestClient(app) as client:
        h = drive_session(client, bearer(read_value))
        refused = call_tool(client, h, 2, "set_direction", {"mission": "M1", "change_note": "init"})
        allowed = call_tool(client, h, 3, "get_constitution", {})

    assert refused.status_code == 403
    assert "scope does not cover" in refused.text
    assert allowed.status_code == 200
    assert store.head("default") is None


def test_given_an_expired_token_asking_to_write_when_posting_then_it_is_401_not_403():
    # Authentication is checked before scope: a dead token is refused as
    # unknown (401) even when the body asks for set_direction. Answering
    # 403 would confirm the token once existed.
    from starlette.testclient import TestClient

    store, _value, app = gated_http_app()
    expired = mint(store, name="old", expires_at=datetime.now(UTC) - timedelta(hours=1))

    with TestClient(app) as client:
        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "set_direction", "arguments": {"mission": "M1"}},
            },
            headers=bearer(expired),
        )

    assert response.status_code == 401


def test_given_allow_insecure_when_calling_set_direction_then_the_write_executes(monkeypatch):
    # The documented opt-in: with no token store, nothing is checked and a
    # write goes through. This is what allow_insecure = true buys, and why
    # it warns.
    from starlette.testclient import TestClient

    from kyno.transports import build_http_app

    store = token_store()
    app = build_http_app(ControlPlane(store), allow_insecure=True)

    with TestClient(app) as client:
        h = drive_session(client, MCP_HEADERS)
        response = call_tool(
            client, h, 2, "set_direction", {"mission": "M1", "change_note": "init"}
        )

    assert response.status_code == 200
    assert store.head("default").mission == "M1"


def test_given_allow_insecure_when_calling_an_undeclared_tool_then_the_server_itself_refuses():
    # With the check off there is no scope to fail closed on: the request
    # passes the endpoint, and the server answers with its own unknown-tool
    # error inside the protocol instead of a 403 at the door.
    from starlette.testclient import TestClient

    from kyno.transports import build_http_app

    store = token_store()
    app = build_http_app(ControlPlane(store), allow_insecure=True)

    with TestClient(app) as client:
        h = drive_session(client, MCP_HEADERS)
        response = call_tool(client, h, 2, "not_a_declared_tool", {})

    assert response.status_code == 200
    result = sse_json(response.text)["result"]
    assert result["isError"] is True
    assert "unknown tool" in result["content"][0]["text"]


def test_given_authorized_requests_when_they_arrive_then_last_used_moves_once_per_window():
    from starlette.testclient import TestClient

    store, value, app = gated_http_app()

    with TestClient(app) as client:
        client.post("/mcp", json=initialize_payload(), headers=bearer(value))
        first = store.tokens()[0].last_used_at
        client.post("/mcp", json=initialize_payload(), headers=bearer(value))
        second = store.tokens()[0].last_used_at

    assert first is not None
    # The second request arrives inside the five-minute window, so the
    # stored value is not updated.
    assert second == first


def test_given_a_content_length_over_the_size_cap_when_posting_then_it_is_413_unread():
    from starlette.testclient import TestClient

    from kyno.transports import MAX_MCP_BODY_BYTES

    _store, value, app = gated_http_app()

    with TestClient(app) as client:
        response = client.post(
            "/mcp", content=b"x" * (MAX_MCP_BODY_BYTES + 1), headers=bearer(value)
        )

    assert response.status_code == 413


def test_given_a_content_length_at_the_size_cap_when_posting_then_it_is_not_413():
    from starlette.testclient import TestClient

    from kyno.transports import MAX_MCP_BODY_BYTES

    _store, value, app = gated_http_app()

    with TestClient(app) as client:
        response = client.post("/mcp", content=b"x" * MAX_MCP_BODY_BYTES, headers=bearer(value))

    # Not valid JSON-RPC, so the MCP layer refuses it -- but as a bad
    # request, never as too large and never as a server error.
    assert response.status_code not in (413, 500)


def test_given_a_chunked_body_crossing_the_size_cap_when_streaming_then_it_is_413():
    # Chunked transfer declares no Content-Length, so only counting the
    # streamed bytes can enforce the cap.
    from starlette.testclient import TestClient

    from kyno.transports import MAX_MCP_BODY_BYTES

    _store, value, app = gated_http_app()
    chunk = b"x" * (MAX_MCP_BODY_BYTES // 4 + 1)

    with TestClient(app) as client:
        response = client.post("/mcp", content=iter([chunk] * 5), headers=bearer(value))

    assert "content-length" not in response.request.headers
    assert response.status_code == 413


def test_given_a_chunked_body_under_the_size_cap_when_streaming_then_it_reaches_the_mcp_handler():
    from starlette.testclient import TestClient

    _store, value, app = gated_http_app()
    body = json.dumps(initialize_payload()).encode()
    middle = len(body) // 2

    with TestClient(app) as client:
        response = client.post(
            "/mcp", content=iter([body[:middle], body[middle:]]), headers=bearer(value)
        )

    assert response.status_code == 200
    assert '"serverInfo"' in response.text
