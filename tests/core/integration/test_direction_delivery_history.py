"""Core records runtime MCP responses and exposes their history without recording queries."""

import json

import mcp.types as types
import pytest

from kyno.delivery import DeliveryHistory
from kyno.mcp_server import build_server
from kyno.service import ControlPlane
from kyno.store.sql import SqlConstitutionStore
from kyno.wire import RESOURCE_URI


@pytest.fixture
def history_store():
    store = SqlConstitutionStore(url="sqlite://")
    store.create_all()
    yield store
    store.engine.dispose()


def server_with_history(store, policy="always", constitution="default"):
    history = DeliveryHistory(store.engine, policy=policy)
    plane = ControlPlane(store, constitution, delivery_history=history)
    plane.set_direction(
        mission="Help customers",
        principles=["Be clear"],
        declaration="Explain the options",
        change_note="initial",
        constitution=constitution,
    )
    return build_server(plane), history, plane


async def invoke(server, name, arguments=None):
    response = await server.request_handlers[types.CallToolRequest](
        types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(name=name, arguments=arguments or {}),
        )
    )
    assert not response.root.isError, response.root.content
    return json.loads(response.root.content[0].text)


@pytest.mark.asyncio
async def test_given_default_recording_when_reading_direction_then_no_history_is_written(
    history_store,
):
    server, history, _ = server_with_history(history_store, policy="never")
    result = await invoke(server, "get_constitution")
    assert result["recording"] == {"status": "disabled", "delivery_id": None}
    assert history.list()["items"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,arguments",
    [
        ("get_constitution", {"detail": "full"}),
        ("get_changes_since", {"known_version": 0}),
        ("get_mission", {}),
        ("get_declaration", {}),
        ("get_principles", {"detail": "titles"}),
        ("get_principle", {"title": "Be clear"}),
    ],
)
async def test_given_recording_enabled_when_reading_then_history_matches_the_exact_response(
    history_store,
    operation,
    arguments,
):
    server, history, _ = server_with_history(history_store)
    result = await invoke(
        server,
        operation,
        {
            **arguments,
            "session_id": "agent-session",
            "metadata": {"app": {"trial": [1, 2]}},
        },
    )
    recording = result.pop("recording")
    assert recording["status"] == "recorded"
    record = history.get(recording["delivery_id"])
    assert record["direction"] == result
    assert record["served_version"] == 1
    assert record["operation"] == operation
    assert record["session_id"] == "agent-session"
    assert record["metadata"] == {"app": {"trial": [1, 2]}}
    assert record["requester"] is None
    assert record["constitution_id"] is not None
    assert record["known_version"] == arguments.get("known_version")


@pytest.mark.asyncio
async def test_given_unchanged_direction_when_pulling_twice_then_each_response_has_its_own_record(
    history_store,
):
    server, history, _ = server_with_history(history_store)
    first = await invoke(server, "get_constitution")
    second = await invoke(server, "get_constitution")
    assert first["recording"]["delivery_id"] != second["recording"]["delivery_id"]
    assert len(history.list()["items"]) == 2


@pytest.mark.asyncio
async def test_given_a_saved_response_when_direction_changes_then_its_content_stays_unchanged(
    history_store,
):
    server, history, plane = server_with_history(history_store)
    response = await invoke(server, "get_constitution")
    plane.set_direction(mission="Resolve complaints", change_note="new priority")
    record = history.get(response["recording"]["delivery_id"])
    assert record["direction"]["mission"] == "Help customers"
    assert record["served_version"] == 1


@pytest.mark.asyncio
async def test_given_an_unknown_name_when_reading_then_the_record_has_no_constitution_id(
    history_store,
):
    server, history, _ = server_with_history(history_store)
    result = await invoke(server, "get_constitution", {"constitution": "missing"})
    record = history.get(result["recording"]["delivery_id"])
    assert record["constitution_id"] is None
    assert record["requested_constitution"] == "missing"
    assert record["served_version"] == 0
    assert history_store.head("missing") is None


@pytest.mark.asyncio
async def test_given_a_delivery_when_querying_history_then_no_more_records_are_created(
    history_store,
):
    server, history, _ = server_with_history(history_store)
    response = await invoke(server, "get_constitution")
    identifier = response["recording"]["delivery_id"]
    assert await invoke(server, "get_delivery", {"delivery_id": identifier}) == history.get(
        identifier
    )
    assert len((await invoke(server, "list_deliveries"))["items"]) == 1
    assert len(history.list()["items"]) == 1


@pytest.mark.asyncio
async def test_given_recording_enabled_when_reading_the_mcp_resource_then_the_response_is_recorded(
    history_store,
):
    server, history, _ = server_with_history(history_store, constitution="support")
    result = await server.request_handlers[types.ReadResourceRequest](
        types.ReadResourceRequest(
            method="resources/read",
            params=types.ReadResourceRequestParams(uri=RESOURCE_URI),
        )
    )
    payload = json.loads(result.root.contents[0].text)
    record = history.get(payload["recording"]["delivery_id"])
    assert record["requested_constitution"] == "support"
    assert record["operation"] == "read_resource"


@pytest.mark.asyncio
async def test_given_a_failed_insert_when_reading_then_direction_returns_without_error_details(
    history_store, monkeypatch, caplog
):
    server, history, _ = server_with_history(history_store)

    def fail_insert(**values):
        raise RuntimeError("password=secret-value")

    monkeypatch.setattr(history, "_insert", fail_insert)
    response = await invoke(server, "get_constitution")
    assert response["mission"] == "Help customers"
    assert response["recording"] == {"status": "failed", "delivery_id": None}
    assert history.list()["items"] == []
    assert "delivery_recording_failed" in caplog.text
    assert "secret-value" not in caplog.text


@pytest.mark.asyncio
async def test_given_a_client_policy_override_when_reading_then_the_server_still_records(
    history_store,
):
    server, history, _ = server_with_history(history_store)
    response = await invoke(server, "get_constitution", {"recording_policy": "never"})
    assert response["recording"]["status"] == "recorded"
    assert len(history.list()["items"]) == 1


@pytest.mark.asyncio
async def test_given_multiple_sessions_when_filtering_and_paging_then_only_matches_are_returned(
    history_store,
):
    server, history, _ = server_with_history(history_store)
    identifiers = []
    for session in ("first", "second", "first"):
        result = await invoke(server, "get_constitution", {"session_id": session})
        identifiers.append(result["recording"]["delivery_id"])
    first = history.list(session_id="first", constitution="default", limit=1)
    assert [row["delivery_id"] for row in first["items"]] == identifiers[:1]
    second = history.list(session_id="first", after=first["next_cursor"], limit=1)
    assert [row["delivery_id"] for row in second["items"]] == identifiers[2:]
    assert second["next_cursor"] is None
    assert history.list(constitution="absent")["items"] == []
    timestamp = history.get(identifiers[1])["recorded_at"]
    assert [
        row["delivery_id"] for row in history.list(since=timestamp, until=timestamp)["items"]
    ] == identifiers[1:2]


@pytest.mark.asyncio
async def test_given_history_when_recording_is_disabled_then_old_records_remain_queryable(
    history_store,
):
    server, history, plane = server_with_history(history_store)
    recorded = await invoke(server, "get_constitution")
    plane.delivery_history = DeliveryHistory(history_store.engine)
    result = await invoke(server, "get_constitution")
    assert result["recording"]["status"] == "disabled"
    assert plane.delivery_history.get(recorded["recording"]["delivery_id"])
    assert len(history.list()["items"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,arguments",
    [
        ("get_principle", {"title": "missing"}),
        ("get_changes_since", {"known_version": 100}),
        ("get_constitution", {"metadata": []}),
    ],
)
async def test_given_an_invalid_read_when_calling_core_then_no_delivery_is_recorded(
    history_store,
    operation,
    arguments,
):
    server, history, _ = server_with_history(history_store)
    result = await server.request_handlers[types.CallToolRequest](
        types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(name=operation, arguments=arguments),
        )
    )
    assert result.root.isError
    assert history.list()["items"] == []


@pytest.mark.parametrize(
    "arguments",
    [
        {"limit": 0},
        {"limit": 101},
        {"limit": True},
        {"after": -1},
        {"after": False},
        {"since": "not a date"},
        {"until": "2026-09-12"},
        {"since": "2026-09-13T00:00:00Z", "until": "2026-09-12T00:00:00Z"},
    ],
)
def test_given_invalid_history_filters_when_listing_then_the_query_is_rejected(
    history_store, arguments
):
    history = DeliveryHistory(history_store.engine)
    with pytest.raises(ValueError):
        history.list(**arguments)


def test_given_an_unknown_delivery_id_when_retrieving_then_not_found_is_reported(history_store):
    with pytest.raises(ValueError, match="not found"):
        DeliveryHistory(history_store.engine).get("missing")


@pytest.mark.asyncio
async def test_given_a_dropped_history_table_when_reading_then_direction_still_returns(
    history_store,
):
    server, history, _ = server_with_history(history_store)
    history_store.metadata.tables["kyno_deliveries"].drop(history_store.engine)
    response = await invoke(server, "get_constitution")
    assert response["recording"] == {"status": "failed", "delivery_id": None}
    assert response["mission"] == "Help customers"
    assert history_store.head("default").version == 1


@pytest.mark.asyncio
async def test_given_published_direction_when_exporting_then_no_runtime_delivery_is_recorded(
    history_store,
):
    server, history, plane = server_with_history(history_store)
    plane.publish("default")
    assert len(await invoke(server, "export_versions")) == 1
    assert plane.public_constitution("default") is not None
    assert history.list()["items"] == []


@pytest.mark.asyncio
async def test_given_failed_attribution_when_reading_then_direction_returns_with_failed_recording(
    history_store,
    monkeypatch,
):
    import kyno.mcp_server as module

    server, history, _ = server_with_history(history_store)

    def fail_attribution(*args):
        raise RuntimeError("private connection detail")

    monkeypatch.setattr(module, "_request_token", fail_attribution)
    result = await invoke(server, "get_constitution")
    assert result["mission"] == "Help customers"
    assert result["recording"] == {"status": "failed", "delivery_id": None}
    assert history.list()["items"] == []


@pytest.mark.asyncio
async def test_given_irrelevant_arguments_when_reading_mission_then_they_cannot_disable_recording(
    history_store,
):
    server, history, _ = server_with_history(history_store)
    response = await invoke(
        server,
        "get_mission",
        {
            "known_version": {"bad": 1},
            "detail": ["invalid"],
            "title": "not requested",
        },
    )
    assert response["recording"]["status"] == "recorded"
    record = history.get(response["recording"]["delivery_id"])
    assert record["known_version"] is None
    assert record["detail_level"] is None
    assert record["selection"] == {}


@pytest.mark.asyncio
async def test_given_a_prior_delivery_when_reviewing_after_restart_then_original_direction_returns(
    history_store,
):
    server, _, plane = server_with_history(history_store)
    response = await invoke(server, "get_constitution", {"detail": "full"})
    identifier = response.pop("recording")["delivery_id"]
    plane.set_direction(mission="Handle urgent complaints", change_note="new priority")
    restarted = build_server(
        ControlPlane(history_store, delivery_history=DeliveryHistory(history_store.engine))
    )
    record = await invoke(restarted, "get_delivery", {"delivery_id": identifier})
    assert record["direction"] == response
    assert record["served_version"] == 1
    assert plane.current().version == 2
