"""Authorized MCP clients retrieve persisted delivery snapshots safely."""

import json

import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from starlette.testclient import TestClient

from kyno.delivery import RecordingPolicy
from kyno.delivery_recording import DeliveryRecorder
from kyno.mcp_server import build_server
from kyno.service import ControlPlane
from kyno.store.delivery_record import SqlDeliveryRecordStore
from kyno.store.sql import SqlConstitutionStore
from kyno.transports import build_http_app
from tests.mcp_requests import bearer, call_tool, drive_session, mint, sse_json, token_store


@pytest.fixture
def delivery_setup():
    store = token_store()
    deliveries = SqlDeliveryRecordStore(store.engine)
    identifier = deliveries.append(
        {"version": 0, "mission": "Original"},
        operation="get_mission",
        constitution="default",
        arguments={},
        context={"session_id": None, "metadata": {}},
    )
    try:
        yield store, deliveries, identifier
    finally:
        store.engine.dispose()


@pytest.mark.parametrize("scope", ["read", "write"])
def test_given_authorized_token_when_getting_delivery_then_snapshot_returns(delivery_setup, scope):
    store, deliveries, identifier = delivery_setup
    app = build_http_app(ControlPlane(store, delivery_record_store=deliveries), token_store=store)
    value = mint(store, scope=scope)
    with TestClient(app) as client:
        headers = drive_session(client, bearer(value))
        response = call_tool(client, headers, 2, "get_delivery_record", {"record_id": identifier})
    result = sse_json(response.text)["result"]
    assert not result.get("isError")
    assert json.loads(result["content"][0]["text"]) == deliveries.get(identifier)
    with store.engine.connect() as connection:
        assert (
            len(connection.execute(select(store.metadata.tables["kyno_delivery_records"])).all())
            == 1
        )


async def test_given_lookup_tool_when_listing_then_required_id_is_declared(delivery_setup):
    store, deliveries, _ = delivery_setup
    async with create_connected_server_and_client_session(
        build_server(ControlPlane(store, delivery_record_store=deliveries))
    ) as client:
        tools = await client.list_tools()
    tool = next(tool for tool in tools.tools if tool.name == "get_delivery_record")
    assert tool.inputSchema["required"] == ["record_id"]
    assert tool.inputSchema["properties"]["record_id"]["type"] == "string"


@pytest.mark.parametrize("arguments", [{}, {"record_id": "unknown"}])
async def test_given_missing_or_unknown_id_when_getting_delivery_then_error_returns(
    delivery_setup, arguments
):
    store, deliveries, _ = delivery_setup
    async with create_connected_server_and_client_session(
        build_server(ControlPlane(store, delivery_record_store=deliveries))
    ) as client:
        result = await client.call_tool("get_delivery_record", arguments)
    assert result.isError
    if arguments:
        assert result.content[0].text == "delivery record not found"
    else:
        assert "record_id" in result.content[0].text


async def test_given_unconfigured_history_when_getting_delivery_then_configuration_error_is_safe():
    async with create_connected_server_and_client_session(
        build_server(ControlPlane(token_store()))
    ) as client:
        result = await client.call_tool("get_delivery_record", {"record_id": "unknown"})
    assert result.isError
    assert result.content[0].text == "delivery history is not configured on this Core instance"


async def test_given_database_failure_when_getting_delivery_then_secrets_are_hidden(
    delivery_setup, monkeypatch
):
    store, deliveries, identifier = delivery_setup

    def fail(record_id):
        raise OperationalError("SELECT secret", {}, Exception("password=secret"))

    monkeypatch.setattr(deliveries, "get", fail)
    async with create_connected_server_and_client_session(
        build_server(ControlPlane(store, delivery_record_store=deliveries))
    ) as client:
        result = await client.call_tool("get_delivery_record", {"record_id": identifier})
    assert result.isError
    assert result.content[0].text == "delivery history is unavailable"


@pytest.mark.parametrize("credential", ["invalid", "missing", "revoked"])
def test_given_unauthorized_token_when_getting_delivery_then_access_is_denied(
    delivery_setup, credential
):
    store, deliveries, identifier = delivery_setup
    app = build_http_app(ControlPlane(store, delivery_record_store=deliveries), token_store=store)
    headers = bearer("invalid")
    if credential == "missing":
        headers.pop("Authorization")
    elif credential == "revoked":
        headers = bearer(mint(store))
        store.revoke_token(store.tokens()[0].id)
    with TestClient(app) as client:
        response = call_tool(client, headers, 2, "get_delivery_record", {"record_id": identifier})
    assert response.status_code == 401


async def test_given_recorded_direction_when_updated_and_restarted_then_lookup_keeps_original(
    tmp_path,
):
    url = f"sqlite:///{tmp_path / 'restart.sqlite3'}"
    store = SqlConstitutionStore(url=url)
    store.create_all()
    deliveries = SqlDeliveryRecordStore(store.engine)
    core = ControlPlane(
        store,
        delivery_record_store=deliveries,
        delivery_recorder=DeliveryRecorder(deliveries, RecordingPolicy.ALWAYS),
    )
    async with create_connected_server_and_client_session(build_server(core)) as client:
        await client.call_tool(
            "set_direction",
            {
                "mission": "Original mission",
                "declaration": "Original declaration",
                "principles": [{"title": "Honesty", "description": "State the facts."}],
                "change_note": "initial",
            },
        )
        result = await client.call_tool(
            "get_constitution",
            {
                "detail": "full",
                "session_id": "run-1",
                "metadata": {"step": ["first"]},
            },
        )
        original = json.loads(result.content[0].text)
        identifier = original.pop("recording")["record_id"]
        await client.call_tool(
            "set_direction",
            {
                "mission": "New mission",
                "declaration": "New declaration",
                "principles": ["New principle"],
                "change_note": "updated",
            },
        )
    store.engine.dispose()
    restarted_store = SqlConstitutionStore(url=url)
    restarted_deliveries = SqlDeliveryRecordStore(restarted_store.engine)
    restarted = ControlPlane(restarted_store, delivery_record_store=restarted_deliveries)
    async with create_connected_server_and_client_session(build_server(restarted)) as client:
        result = await client.call_tool("get_delivery_record", {"record_id": identifier})
    assert not result.isError
    snapshot = json.loads(result.content[0].text)
    assert snapshot["direction"] == original
    assert snapshot["served_version"] == 1
    assert snapshot["session_id"] == "run-1"
    assert snapshot["metadata"] == {"step": ["first"]}
    assert restarted.current().version == 2
    restarted_store.engine.dispose()


async def test_given_always_recording_when_getting_delivery_then_history_read_is_not_recorded(
    delivery_setup,
):
    store, deliveries, identifier = delivery_setup
    core = ControlPlane(
        store,
        delivery_record_store=deliveries,
        delivery_recorder=DeliveryRecorder(deliveries, RecordingPolicy.ALWAYS),
    )
    async with create_connected_server_and_client_session(build_server(core)) as client:
        result = await client.call_tool("get_delivery_record", {"record_id": identifier})
    assert not result.isError
    assert "recording" not in json.loads(result.content[0].text)
    with store.engine.connect() as connection:
        assert connection.execute(
            select(store.metadata.tables["kyno_delivery_records"].c.record_id)
        ).scalars().all() == [identifier]
