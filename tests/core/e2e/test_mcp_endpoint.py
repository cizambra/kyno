"""Authenticated HTTP client sessions through the MCP endpoint."""

import json
import logging

import pytest

from kyno.delivery import DeliveryHistory
from kyno.service import ControlPlane
from kyno.transports import build_http_app
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
def test_given_a_read_token_when_fetching_delivery_history_then_server_identity_is_preserved():
    from starlette.testclient import TestClient

    store, writer, _ = gated_http_app()
    reader = mint(store, scope="read", name="agents")
    history = DeliveryHistory(store.engine, policy="always")
    plane = ControlPlane(store, delivery_history=history)
    plane.set_direction(mission="Support customers", change_note="initial")
    app = build_http_app(plane, token_store=store)
    with TestClient(app) as client:
        headers = drive_session(client, bearer(reader))
        response = call_tool(
            client,
            headers,
            2,
            "get_mission",
            {
                "session_id": "application-session",
                "metadata": {"requester": "forged", "id": 999},
                "recording_policy": "never",
            },
        )
        direction = json.loads(sse_json(response.text)["result"]["content"][0]["text"])
        identifier = direction["recording"]["delivery_id"]
        fetched = call_tool(client, headers, 3, "get_delivery", {"delivery_id": identifier})
        record = json.loads(sse_json(fetched.text)["result"]["content"][0]["text"])
        assert record["requester"] == {
            "id": store.tokens()[1].id,
            "name": "agents",
            "scope": "read",
        }
        assert record["metadata"] == {"requester": "forged", "id": 999}
        assert record["direction"] == {"version": 1, "mission": "Support customers"}
        assert reader not in fetched.text and writer not in fetched.text
        listed = call_tool(
            client, headers, 4, "list_deliveries", {"session_id": "application-session"}
        )
        assert len(json.loads(sse_json(listed.text)["result"]["content"][0]["text"])["items"]) == 1
        refused = call_tool(
            client, headers, 5, "set_direction", {"mission": "No", "change_note": "No"}
        )
        assert refused.status_code == 403
        missing_auth = call_tool(
            client,
            {key: value for key, value in headers.items() if key != "Authorization"},
            6,
            "get_delivery",
            {"delivery_id": identifier},
        )
        assert missing_auth.status_code == 401
    assert len(history.list()["items"]) == 1


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
