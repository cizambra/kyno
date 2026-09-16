"""Runtime MCP reads persist version references with caller context and recording status."""

import json
from unittest.mock import Mock

import mcp.types as types
import pytest
from sqlalchemy import select

from kyno.delivery_recording import DeliveryRecorder
from kyno.mcp.server import build_server
from kyno.mcp.tools import DIRECTION_READS, TOOLS
from kyno.service import ControlPlane
from kyno.store.delivery_record import SqlDeliveryRecordStore
from kyno.wire import RESOURCE_URI


def server_with_history(store, policy="always", constitution="default"):
    history = SqlDeliveryRecordStore(store.engine, recording_url=store.engine.url)
    plane = ControlPlane(
        store,
        constitution,
        delivery_recorder=DeliveryRecorder(history, policy),
        delivery_record_store=history,
    )
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


def records(store):
    with store.engine.connect() as connection:
        return (
            connection.execute(select(store.metadata.tables["kyno_delivery_records"]))
            .mappings()
            .all()
        )


def saved_record(store, identifier):
    return SqlDeliveryRecordStore(store.engine).get(identifier)


@pytest.mark.asyncio
async def test_given_default_recording_when_reading_direction_then_no_history_is_written(
    memory_store,
):
    server, history, _ = server_with_history(memory_store, policy="never")
    result = await invoke(server, "get_constitution")
    assert result["recording"] == {"status": "disabled", "record_id": None}
    assert records(memory_store) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("known_version", [None, 0, 1])
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
async def test_given_recording_enabled_when_reading_then_history_keeps_the_served_version_and_delta(
    memory_store,
    operation,
    arguments,
    known_version,
):
    arguments = {
        **arguments,
        **({"known_version": known_version} if known_version is not None else {}),
    }
    server, history, _ = server_with_history(memory_store)
    result = await invoke(
        server,
        operation,
        {
            **arguments,
            "correlation_id": "agent-session",
            "metadata": {"app": {"trial": [1, 2]}},
        },
    )
    recording = result.pop("recording")
    assert recording["status"] == "recorded"
    record = saved_record(memory_store, recording["record_id"])
    assert "direction" not in record
    assert record["delta"] == result.get("delta")
    assert record["served_version"] == 1
    assert record["operation"] == operation
    assert record["correlation_id"] == "agent-session"
    assert record["metadata"] == {"app": {"trial": [1, 2]}}
    assert record["requester"] is None
    assert record["constitution_id"] is not None
    assert record["known_version"] == arguments.get("known_version")


@pytest.mark.asyncio
async def test_given_unchanged_direction_when_pulling_twice_then_each_response_has_its_own_record(
    memory_store,
):
    server, history, _ = server_with_history(memory_store)
    first = await invoke(server, "get_constitution")
    second = await invoke(server, "get_constitution")
    assert first["recording"]["record_id"] != second["recording"]["record_id"]
    assert len(records(memory_store)) == 2


@pytest.mark.asyncio
async def test_given_later_direction_when_getting_delivery_then_original_version_remains_available(
    memory_store,
):
    server, history, plane = server_with_history(memory_store)
    response = await invoke(server, "get_constitution")
    plane.set_direction(mission="Resolve complaints", change_note="new priority")
    record = saved_record(memory_store, response["recording"]["record_id"])
    assert memory_store.get("default", record["served_version"]).mission == "Help customers"
    assert "direction" not in record
    assert record["served_version"] == 1


@pytest.mark.asyncio
async def test_given_a_known_version_when_recording_changes_then_the_returned_delta_is_preserved(
    memory_store,
):
    server, history, plane = server_with_history(memory_store)
    plane.set_direction(mission="Resolve complaints", change_note="new priority")
    response = await invoke(server, "get_changes_since", {"known_version": 1, "detail": "full"})
    record_id = response["recording"]["record_id"]
    assert response["delta"]
    plane.set_direction(mission="Prevent complaints", change_note="next priority")
    record = history.get(record_id)
    assert record["known_version"] == 1
    assert record["served_version"] == 2
    assert record["delta"] == response["delta"]
    assert "direction" not in record
    assert "change_notes" not in record
    assert memory_store.get("default", 2).mission == "Resolve complaints"


@pytest.mark.asyncio
async def test_given_an_unknown_name_when_reading_then_the_record_has_no_constitution_id(
    memory_store,
):
    server, history, _ = server_with_history(memory_store)
    result = await invoke(server, "get_constitution", {"constitution": "missing"})
    record = saved_record(memory_store, result["recording"]["record_id"])
    assert record["constitution_id"] is None
    assert record["requested_constitution"] == "missing"
    assert record["served_version"] == 0
    assert memory_store.head("missing") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["recorded", "disabled", "failed"])
async def test_given_recording_outcome_when_reading_resource_then_direction_and_status_are_returned(
    memory_store,
    monkeypatch,
    status,
):
    server, history, _ = server_with_history(
        memory_store, policy="never" if status == "disabled" else "always", constitution="support"
    )
    append = Mock(wraps=history.append)
    if status == "failed":
        append.side_effect = RuntimeError("database unavailable")
    monkeypatch.setattr(history, "append", append)
    result = await server.request_handlers[types.ReadResourceRequest](
        types.ReadResourceRequest(
            method="resources/read",
            params=types.ReadResourceRequestParams(uri=RESOURCE_URI),
        )
    )
    payload = json.loads(result.root.contents[0].text)
    assert payload["mission"] == "Help customers"
    assert payload["version"] == 1
    assert payload["recording"]["status"] == status
    assert append.call_count == (0 if status == "disabled" else 1)
    if status != "recorded":
        assert payload["recording"]["record_id"] is None
        assert records(memory_store) == []
        return
    record = saved_record(memory_store, payload["recording"]["record_id"])
    assert record["requested_constitution"] == "support"
    assert record["operation"] == "read_resource"
    assert record["detail_level"] == "compact"
    assert record["correlation_id"] is None
    assert record["metadata"] == {}


@pytest.mark.asyncio
async def test_given_a_failed_insert_when_reading_then_direction_returns_without_error_details(
    memory_store, monkeypatch, caplog
):
    server, history, _ = server_with_history(memory_store)

    def fail_insert(*args, **values):
        raise RuntimeError("password=secret-value")

    monkeypatch.setattr(history, "append", fail_insert)
    response = await invoke(server, "get_constitution")
    assert response["mission"] == "Help customers"
    assert response["recording"] == {"status": "failed", "record_id": None}
    assert records(memory_store) == []
    assert "delivery_recording_failed" in caplog.text
    assert "secret-value" not in caplog.text


@pytest.mark.asyncio
async def test_given_a_client_policy_override_when_reading_then_the_server_still_records(
    memory_store,
):
    server, history, _ = server_with_history(memory_store)
    response = await invoke(server, "get_constitution", {"recording_policy": "never"})
    assert response["recording"]["status"] == "recorded"
    assert len(records(memory_store)) == 1


@pytest.mark.asyncio
async def test_given_history_when_recording_is_disabled_then_old_records_remain_queryable(
    memory_store,
):
    server, history, plane = server_with_history(memory_store)
    recorded = await invoke(server, "get_constitution")
    plane.delivery_recorder = DeliveryRecorder(SqlDeliveryRecordStore(memory_store.engine))
    result = await invoke(server, "get_constitution")
    assert result["recording"]["status"] == "disabled"
    assert saved_record(memory_store, recorded["recording"]["record_id"])
    assert len(records(memory_store)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,arguments",
    [
        ("get_principle", {"title": "missing"}),
        ("get_changes_since", {"known_version": 100}),
        ("get_constitution", {"metadata": []}),
        ("get_constitution", {"metadata": {"large": "x" * 16384}}),
        ("get_constitution", {"metadata": {"number": float("nan")}}),
        ("get_constitution", {"correlation_id": "x" * 256}),
        ("get_mission", {"known_version": True}),
        ("get_mission", {"known_version": "1"}),
        ("get_mission", {"known_version": 1.5}),
        ("get_mission", {"known_version": {"bad": 1}}),
        ("get_mission", {"known_version": None}),
    ],
)
async def test_given_an_invalid_read_when_calling_core_then_no_delivery_is_recorded(
    memory_store,
    operation,
    arguments,
):
    server, history, _ = server_with_history(memory_store)
    result = await server.request_handlers[types.CallToolRequest](
        types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(name=operation, arguments=arguments),
        )
    )
    assert result.root.isError
    assert records(memory_store) == []


@pytest.mark.asyncio
async def test_given_a_dropped_history_table_when_reading_then_direction_still_returns(
    memory_store,
):
    server, history, _ = server_with_history(memory_store)
    memory_store.metadata.tables["kyno_delivery_records"].drop(memory_store.engine)
    response = await invoke(server, "get_constitution")
    assert response["recording"] == {"status": "failed", "record_id": None}
    assert response["mission"] == "Help customers"
    assert memory_store.head("default").version == 1


@pytest.mark.asyncio
async def test_given_published_direction_when_exporting_then_no_runtime_delivery_is_recorded(
    memory_store,
):
    server, history, plane = server_with_history(memory_store)
    plane.publish("default")
    assert len(await invoke(server, "export_versions")) == 1
    assert plane.public_constitution("default") is not None
    assert records(memory_store) == []


@pytest.mark.asyncio
async def test_given_failed_attribution_when_reading_then_direction_returns_with_failed_recording(
    memory_store,
    monkeypatch,
):
    import kyno.mcp.request_context as module

    server, history, _ = server_with_history(memory_store)

    def fail_attribution(*args):
        raise RuntimeError("private connection detail")

    monkeypatch.setattr(module, "_request_token", fail_attribution)
    result = await invoke(server, "get_constitution")
    assert result["mission"] == "Help customers"
    assert result["recording"] == {"status": "failed", "record_id": None}
    assert records(memory_store) == []


@pytest.mark.asyncio
async def test_given_irrelevant_arguments_when_reading_mission_then_they_cannot_disable_recording(
    memory_store,
):
    server, history, _ = server_with_history(memory_store)
    response = await invoke(
        server,
        "get_mission",
        {
            "detail": ["invalid"],
            "title": "not requested",
        },
    )
    assert response["recording"]["status"] == "recorded"
    record = saved_record(memory_store, response["recording"]["record_id"])
    assert record["known_version"] is None
    assert record["detail_level"] is None
    assert record["selection"] == {}


@pytest.mark.parametrize("operation", sorted(DIRECTION_READS))
def test_given_direction_tool_when_listing_schema_then_caller_version_is_declared(operation):
    schema = next(tool.inputSchema for tool in TOOLS if tool.name == operation)
    assert schema["properties"]["known_version"]["type"] == "integer"
    assert ("known_version" in schema.get("required", [])) == (operation == "get_changes_since")


@pytest.mark.parametrize("policy", ["never", "always"])
@pytest.mark.asyncio
async def test_given_workspace_policy_when_composing_server_then_reads_follow_it(
    memory_store, policy
):
    from kyno.delivery import DeliverySettings
    from kyno.public_page import PageConfig
    from kyno.server_config import Settings, control_plane_from_settings

    settings = Settings(
        "sqlite://", "localhost", 2256, PageConfig(), delivery=DeliverySettings(policy)
    )
    plane = control_plane_from_settings(settings, memory_store)
    response = await invoke(build_server(plane), "get_constitution")
    assert response["recording"]["status"] == ("recorded" if policy == "always" else "disabled")
    assert plane.delivery_record_store is not None


@pytest.mark.parametrize("timeout", [0.025, 2.5])
@pytest.mark.asyncio
async def test_given_workspace_timeout_when_reading_direction_then_recording_uses_that_limit(
    memory_store, monkeypatch, timeout
):
    from kyno.delivery import DeliverySettings
    from kyno.public_page import PageConfig
    from kyno.server_config import Settings, control_plane_from_settings

    settings = Settings(
        "sqlite://",
        "localhost",
        2256,
        PageConfig(),
        delivery=DeliverySettings("always", recording_timeout_seconds=timeout),
    )
    plane = control_plane_from_settings(settings, memory_store)
    append = Mock(wraps=plane.delivery_record_store.append)
    monkeypatch.setattr(plane.delivery_record_store, "append", append)
    response = await invoke(build_server(plane), "get_mission")
    assert response["recording"]["status"] == "recorded"
    assert append.call_args.kwargs["timeout_seconds"] == timeout


@pytest.mark.parametrize("policy", ["never", "always"])
@pytest.mark.asyncio
async def test_given_locked_recording_database_when_reading_over_mcp_then_direction_still_returns(
    tmp_path, policy
):
    from kyno.delivery import DeliverySettings
    from kyno.public_page import PageConfig
    from kyno.server_config import Settings, control_plane_from_settings, store_from_settings

    settings = Settings(
        f"sqlite:///{tmp_path / 'kyno.db'}",
        "localhost",
        2256,
        PageConfig(),
        delivery=DeliverySettings(policy, recording_timeout_seconds=0.025),
    )
    store = store_from_settings(settings)
    store.create_all()
    try:
        plane = control_plane_from_settings(settings, store)
        plane.set_direction(mission="Help customers", change_note="initial")
        server = build_server(plane)
        with store.engine.connect() as lock:
            lock.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                response = await invoke(server, "get_mission")
                assert response["mission"] == "Help customers"
                assert response["version"] == 1
                assert response["recording"] == {
                    "status": "failed" if policy == "always" else "disabled",
                    "record_id": None,
                }
            finally:
                lock.rollback()
        assert plane.delivery_record_store.list()["items"] == []
        response = await invoke(server, "get_mission")
        assert response["mission"] == "Help customers"
        assert response["recording"]["status"] == ("recorded" if policy == "always" else "disabled")
    finally:
        store.engine.dispose()


@pytest.mark.asyncio
async def test_given_no_recorder_when_reading_then_status_is_disabled(memory_store):
    response = await invoke(build_server(ControlPlane(memory_store)), "get_constitution")
    assert response["recording"] == {"status": "disabled", "record_id": None}


def test_given_no_recorder_when_recording_through_core_then_status_is_disabled(memory_store):
    result = ControlPlane(memory_store).record_delivery(
        {"version": 0}, operation="get_constitution", arguments={}
    )
    assert result == {"status": "disabled", "record_id": None}


@pytest.mark.asyncio
async def test_given_disabled_recording_when_attribution_fails_then_it_is_not_resolved(
    memory_store, monkeypatch
):
    import kyno.mcp.request_context as module

    server, _, _ = server_with_history(memory_store, policy="never")

    def fail_attribution(*args):
        raise AssertionError("disabled recording must not resolve identity")

    monkeypatch.setattr(module, "_request_token", fail_attribution)
    response = await invoke(server, "get_constitution")
    assert response["recording"]["status"] == "disabled"
