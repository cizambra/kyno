"""Authenticated HTTP client sessions through the MCP endpoint."""

import json
import logging

import pytest

from tests.mcp_requests import bearer, call_tool, drive_session, gated_http_app, mint, sse_json


@pytest.mark.e2e
def test_given_a_write_token_when_driving_an_http_session_then_the_written_mission_is_read_back():
    from starlette.testclient import TestClient

    store, value, app = gated_http_app()

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
    # The version records which token authenticated the write, resolved by
    # the server from the request itself.
    assert store.head("default").token_id == store.tokens()[0].id


@pytest.mark.e2e
def test_given_two_live_tokens_when_writing_with_the_second_then_that_one_is_recorded():
    # With one token in the store, attribution could pass by picking "any
    # token". Two live tokens force the resolution to match the bearer
    # value that actually authenticated the write.
    from starlette.testclient import TestClient

    store, _, app = gated_http_app()
    writer = mint(store, scope="write", name="second")

    with TestClient(app) as client:
        h = drive_session(client, bearer(writer))
        resp = call_tool(client, h, 2, "set_direction", {"mission": "M1", "change_note": "init"})

    assert resp.status_code == 200
    second = next(t for t in store.tokens() if t.name == "second")
    first = next(t for t in store.tokens() if t.name != "second")
    assert store.head("default").token_id == second.id
    assert store.head("default").token_id != first.id


@pytest.mark.e2e
def test_given_a_read_token_when_asking_whoami_over_http_then_its_own_name_and_scope_answer():
    from starlette.testclient import TestClient

    store, _, app = gated_http_app()
    reader = mint(store, scope="read", name="agents")

    with TestClient(app) as client:
        h = drive_session(client, bearer(reader))
        resp = call_tool(client, h, 2, "whoami", {})

    assert resp.status_code == 200
    payload = json.loads(sse_json(resp.text)["result"]["content"][0]["text"])
    row = next(t for t in store.tokens() if t.name == "agents")
    assert payload == {"id": row.id, "name": "agents", "scope": "read"}


@pytest.mark.e2e
def test_given_a_client_claiming_a_token_id_when_writing_then_the_server_ignores_the_claim():
    # token_id is resolved from the request's own bearer header, never from
    # tool arguments: a client cannot attribute its write to another token.
    from starlette.testclient import TestClient

    store, value, app = gated_http_app()
    real_id = store.tokens()[0].id

    with TestClient(app) as client:
        h = drive_session(client, bearer(value))
        call_tool(
            client,
            h,
            2,
            "set_direction",
            {"mission": "M1", "change_note": "init", "token_id": 999},
        )

    head = store.head("default")
    assert head is not None
    assert head.token_id == real_id


@pytest.mark.e2e
def test_given_a_tool_call_when_handled_then_the_request_log_carries_the_fields(caplog):
    from starlette.testclient import TestClient

    store, value, app = gated_http_app()
    token_id = store.tokens()[0].id

    with caplog.at_level(logging.INFO, logger="kyno.requests"), TestClient(app) as client:
        h = drive_session(client, bearer(value))
        call_tool(client, h, 2, "get_constitution", {"constitution": "main"})

    line = next(r.getMessage() for r in caplog.records if "tool=get_constitution" in r.getMessage())
    assert f"token={token_id}" in line
    assert "name=t" in line
    assert "constitution=main" in line
