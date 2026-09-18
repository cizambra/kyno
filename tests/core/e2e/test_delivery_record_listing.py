"""MCP delivery listing preserves query filters and enforces read authorization."""

import json
from unittest.mock import Mock

import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from sqlalchemy import update
from starlette.testclient import TestClient

from kyno.delivery import RecordingPolicy
from kyno.delivery_recording import DeliveryRecorder
from kyno.mcp.server import build_server
from kyno.service import ControlPlane
from kyno.store.delivery_record import SqlDeliveryRecordStore
from kyno.transports import build_http_app
from tests.mcp_requests import bearer, call_tool, drive_session, mint, sse_json
from tests.stores import create_memory_store


@pytest.fixture
def configured():
    store = create_memory_store()
    history = SqlDeliveryRecordStore(store.engine)
    control_plane = ControlPlane(store, delivery_record_store=history)
    identifiers = []
    for session, constitution in [("one", "alpha"), ("two", "beta"), ("one", "alpha")]:
        identifiers.append(
            history.append(
                {"version": 0, "mission": "Not copied", "delta": ["Saved comparison"]},
                operation="get_constitution",
                constitution=constitution,
                arguments={},
                context={"correlation_id": session, "metadata": {}},
            )
        )
    yield store, control_plane, identifiers
    store.engine.dispose()


async def invoke(control_plane, arguments):
    async with create_connected_server_and_client_session(build_server(control_plane)) as client:
        return await client.call_tool("list_delivery_records", arguments)


@pytest.mark.asyncio
async def test_given_delivery_filters_when_reading_next_page_then_only_matching_records_return(
    configured,
):
    _store, control_plane, identifiers = configured
    filters = {
        "correlation_id": "one",
        "constitution": "alpha",
        "since": "2000-01-01T00:00:00Z",
        "until": "9998-01-01T00:00:00Z",
        "limit": 1,
    }
    first = await invoke(control_plane, filters)
    assert not first.isError
    page = json.loads(first.content[0].text)
    assert [item["record_id"] for item in page["items"]] == identifiers[:1]
    assert all("direction" not in item and "delta" not in item for item in page["items"])
    assert control_plane.delivery_record_store.get(identifiers[0])["delta"] == ["Saved comparison"]
    assert page["next_cursor"] is not None
    last = await invoke(control_plane, {**filters, "after": page["next_cursor"]})
    final_page = json.loads(last.content[0].text)
    assert [item["record_id"] for item in final_page["items"]] == identifiers[2:]
    assert all("direction" not in item and "delta" not in item for item in final_page["items"])
    assert final_page["next_cursor"] is None
    assert len(control_plane.delivery_record_store.list()["items"]) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("filters", "positions"),
    [
        ({}, [0, 1, 2]),
        ({"constitution": None}, [0, 1, 2]),
        ({"correlation_id": "two"}, [1]),
        ({"constitution": "beta"}, [1]),
        ({"since": "2026-01-02T00:00:00Z"}, [1, 2]),
        ({"until": "2026-01-02T00:00:00Z"}, [0, 1]),
        ({"constitution": "missing"}, []),
    ],
)
async def test_given_one_history_filter_when_listing_then_only_matching_deliveries_return(
    configured, filters, positions
):
    store, control_plane, identifiers = configured
    table = store.metadata.tables["kyno_delivery_records"]
    with store.engine.begin() as connection:
        for day, identifier in enumerate(identifiers, start=1):
            connection.execute(
                update(table)
                .where(table.c.record_id == identifier)
                .values(recorded_at=f"2026-01-0{day}T00:00:00.000000+00:00")
            )
    result = await invoke(control_plane, filters)
    assert not result.isError
    page = json.loads(result.content[0].text)
    assert [item["record_id"] for item in page["items"]] == [
        identifiers[position] for position in positions
    ]
    assert page["next_cursor"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("arguments", "page_size"), [({}, 50), ({"limit": 1}, 1), ({"limit": 100}, 100)]
)
async def test_given_101_deliveries_when_listing_then_page_size_and_cursor_match_the_limit(
    configured, arguments, page_size
):
    _store, control_plane, identifiers = configured
    history = control_plane.delivery_record_store
    for _ in range(101 - len(identifiers)):
        identifiers.append(
            history.append(
                {"version": 0},
                operation="get_mission",
                constitution="alpha",
                arguments={},
                context={"correlation_id": None, "metadata": {}},
            )
        )
    result = await invoke(control_plane, arguments)
    assert not result.isError
    page = json.loads(result.content[0].text)
    assert [item["record_id"] for item in page["items"]] == identifiers[:page_size]
    assert page["next_cursor"] is not None
    following = await invoke(control_plane, {"after": page["next_cursor"], "limit": 1})
    assert not following.isError
    assert json.loads(following.content[0].text)["items"][0]["record_id"] == identifiers[page_size]


@pytest.mark.asyncio
async def test_given_no_filters_when_listing_over_mcp_then_all_constitutions_are_included(
    configured,
):
    _store, control_plane, identifiers = configured
    result = await invoke(control_plane, {})
    assert not result.isError
    assert [
        item["record_id"] for item in json.loads(result.content[0].text)["items"]
    ] == identifiers


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments",
    [
        {"limit": 0},
        {"limit": 101},
        {"limit": True},
        {"after": -1},
        {"after": "1"},
        {"since": "bad"},
        {"until": "2026-01-01"},
        {"since": "2026-01-02T00:00:00Z", "until": "2026-01-01T00:00:00Z"},
    ],
)
async def test_given_invalid_filters_when_listing_over_mcp_then_tool_returns_an_error(
    configured, arguments
):
    _store, control_plane, _identifiers = configured
    result = await invoke(control_plane, arguments)
    assert result.isError
    assert "unknown tool" not in result.content[0].text


@pytest.mark.asyncio
async def test_given_missing_history_configuration_when_listing_then_error_is_actionable(
    configured,
):
    _store, control_plane, _identifiers = configured
    control_plane.delivery_record_store = None
    result = await invoke(control_plane, {})
    assert result.isError
    assert "delivery history is not configured" in result.content[0].text


@pytest.mark.asyncio
async def test_given_database_failure_when_listing_then_error_hides_database_details(configured):
    store, control_plane, _identifiers = configured
    store.metadata.tables["kyno_delivery_records"].drop(store.engine)
    result = await invoke(control_plane, {})
    assert result.isError
    assert result.content[0].text == "delivery history is unavailable"


@pytest.mark.parametrize("scope", ["read", "write"])
def test_given_authorized_token_when_listing_history_over_http_then_summaries_are_returned(
    configured, scope
):
    store, control_plane, identifiers = configured
    token = mint(store, scope=scope)
    with TestClient(build_http_app(control_plane, token_store=store)) as client:
        headers = drive_session(client, bearer(token))
        response = call_tool(client, headers, 2, "list_delivery_records", {})
    assert response.status_code == 200
    result = sse_json(response.text)["result"]
    assert not result["isError"]
    assert [
        item["record_id"] for item in json.loads(result["content"][0]["text"])["items"]
    ] == identifiers


def test_given_invalid_token_when_listing_history_over_http_then_access_is_denied(configured):
    store, control_plane, _identifiers = configured
    with TestClient(build_http_app(control_plane, token_store=store)) as client:
        response = call_tool(client, bearer("invalid"), 2, "list_delivery_records", {})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_given_always_recording_when_listing_history_then_no_delivery_is_added(
    configured, monkeypatch
):
    _store, control_plane, identifiers = configured
    history = control_plane.delivery_record_store
    control_plane.delivery_recorder = DeliveryRecorder(history, RecordingPolicy.ALWAYS)
    async with create_connected_server_and_client_session(build_server(control_plane)) as client:
        direction = await client.call_tool("get_mission", {})
        recorded_id = json.loads(direction.content[0].text)["recording"]["record_id"]
        append = Mock(side_effect=RuntimeError("recording unavailable"))
        monkeypatch.setattr(history, "append", append)
        result = await client.call_tool("list_delivery_records", {})
    assert not result.isError
    append.assert_not_called()
    page = json.loads(result.content[0].text)
    assert "recording" not in page
    assert [item["record_id"] for item in page["items"]] == [*identifiers, recorded_id]
    assert [item["record_id"] for item in history.list()["items"]] == [*identifiers, recorded_id]
