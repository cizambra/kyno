"""MCP protocol behavior at the server boundary."""

import asyncio
import json

import pytest

from kyno.delivery import RecordingPolicy
from kyno.delivery_recording import DeliveryRecorder
from kyno.mcp import handlers as mcp_handlers, server as mcp_server
from kyno.store.delivery_record import SqlDeliveryRecordStore
from kyno.wire import RESOURCE_URI


@pytest.mark.parametrize(
    "explicit_key",
    [None, "support", "sales"],
    ids=["key-omitted", "matching-key", "conflicting-key"],
)
@pytest.mark.parametrize(
    "operation, required_arguments",
    [
        ("get_constitution", {}),
        ("get_changes_since", {"last_seen_version": 0}),
        ("get_mission", {}),
        ("get_declaration", {}),
        ("get_principles", {}),
        ("get_principle", {"title": "Be clear"}),
        ("export_versions", {}),
        ("list_delivery_records", {}),
        ("apply_direction", {"mission": "Replacement", "change_note": "update"}),
    ],
)
def test_given_constitution_argument_when_call_tool_then_request_is_rejected(
    mcp_runner, operation, required_arguments, explicit_key
):
    runner, control_plane = mcp_runner
    history = SqlDeliveryRecordStore(control_plane._store.engine)
    control_plane.delivery_record_store = history
    control_plane.delivery_recorder = DeliveryRecorder(history, RecordingPolicy.ALWAYS)
    control_plane.apply_direction(mission="Default mission", change_note="initial")
    control_plane.apply_direction(
        constitution_key="support", mission="Support mission", change_note="initial"
    )
    arguments = {**required_arguments, "constitution": "support"}
    if explicit_key is not None:
        arguments["constitution_key"] = explicit_key

    result = runner.call(lambda session: session.call_tool(operation, arguments))

    assert result.isError
    assert "constitution" in result.content[0].text
    assert "should not be valid" in result.content[0].text


@pytest.mark.parametrize(
    "explicit_key",
    [None, "support", "sales"],
    ids=["key-omitted", "matching-key", "conflicting-key"],
)
@pytest.mark.parametrize(
    "operation, required_arguments",
    [
        ("get_constitution", {}),
        ("get_changes_since", {"last_seen_version": 0}),
        ("get_mission", {}),
        ("get_declaration", {}),
        ("get_principles", {}),
        ("get_principle", {"title": "Be clear"}),
        ("export_versions", {}),
        ("list_delivery_records", {}),
        ("apply_direction", {"mission": "Replacement", "change_note": "update"}),
    ],
)
def test_given_constitution_argument_when_call_tool_then_direction_is_unchanged(
    mcp_runner, operation, required_arguments, explicit_key
):
    runner, control_plane = mcp_runner
    history = SqlDeliveryRecordStore(control_plane._store.engine)
    control_plane.delivery_record_store = history
    control_plane.delivery_recorder = DeliveryRecorder(history, RecordingPolicy.ALWAYS)
    control_plane.apply_direction(mission="Default mission", change_note="initial")
    control_plane.apply_direction(
        constitution_key="support", mission="Support mission", change_note="initial"
    )
    arguments = {**required_arguments, "constitution": "support"}
    if explicit_key is not None:
        arguments["constitution_key"] = explicit_key

    runner.call(lambda session: session.call_tool(operation, arguments))

    assert control_plane.current().version == 1
    assert control_plane.current().mission == "Default mission"
    assert control_plane.current("support").version == 1
    assert control_plane.current("support").mission == "Support mission"
    assert control_plane.current("sales").version == 0


@pytest.mark.parametrize(
    "explicit_key",
    [None, "support", "sales"],
    ids=["key-omitted", "matching-key", "conflicting-key"],
)
@pytest.mark.parametrize(
    "operation, required_arguments",
    [
        ("get_constitution", {}),
        ("get_changes_since", {"last_seen_version": 0}),
        ("get_mission", {}),
        ("get_declaration", {}),
        ("get_principles", {}),
        ("get_principle", {"title": "Be clear"}),
        ("export_versions", {}),
        ("list_delivery_records", {}),
        ("apply_direction", {"mission": "Replacement", "change_note": "update"}),
    ],
)
def test_given_constitution_argument_when_call_tool_then_no_delivery_is_recorded(
    mcp_runner, operation, required_arguments, explicit_key
):
    runner, control_plane = mcp_runner
    history = SqlDeliveryRecordStore(control_plane._store.engine)
    control_plane.delivery_record_store = history
    control_plane.delivery_recorder = DeliveryRecorder(history, RecordingPolicy.ALWAYS)
    control_plane.apply_direction(mission="Default mission", change_note="initial")
    control_plane.apply_direction(
        constitution_key="support", mission="Support mission", change_note="initial"
    )
    arguments = {**required_arguments, "constitution": "support"}
    if explicit_key is not None:
        arguments["constitution_key"] = explicit_key

    runner.call(lambda session: session.call_tool(operation, arguments))

    assert history.list()["items"] == []


def test_given_default_direction_when_get_constitution_omits_key_then_default_mission_is_returned(
    mcp_runner,
):
    runner, control_plane = mcp_runner
    control_plane.apply_direction(mission="Default direction", change_note="initial")

    result = runner.call(lambda session: session.call_tool("get_constitution", {}))

    assert not result.isError
    assert json.loads(result.content[0].text)["mission"] == "Default direction"


def test_given_padded_key_when_apply_direction_runs_then_get_constitution_reads_trimmed_key(
    mcp_runner,
):
    runner, control_plane = mcp_runner
    written = runner.call(
        lambda session: session.call_tool(
            "apply_direction",
            {
                "constitution_key": " support ",
                "mission": "Help customers",
                "change_note": "initial",
            },
        )
    )
    assert not written.isError

    result = runner.call(
        lambda session: session.call_tool("get_constitution", {"constitution_key": "support"})
    )

    assert not result.isError
    assert json.loads(result.content[0].text)["mission"] == "Help customers"
    assert control_plane.current().version == 0


def test_given_blank_key_when_apply_direction_runs_then_error_leaves_default_unwritten(mcp_runner):
    runner, control_plane = mcp_runner

    result = runner.call(
        lambda session: session.call_tool(
            "apply_direction",
            {"constitution_key": " ", "mission": "Help customers", "change_note": "initial"},
        )
    )

    assert result.isError
    assert control_plane.current().version == 0


@pytest.mark.parametrize("version", [-1, True, False, 0.0, 1.0, 1.5, "1"])
@pytest.mark.parametrize("operation", ["get_changes_since", "apply_direction"])
def test_given_invalid_version_when_call_tool_is_called_then_request_is_rejected(
    mcp_runner, operation, version
):
    runner, control_plane = mcp_runner
    control_plane.apply_direction(mission="Original", change_note="init")
    arguments = (
        {"last_seen_version": version}
        if operation == "get_changes_since"
        else {"expected_version": version, "mission": "Updated", "change_note": "update"}
    )

    result = runner.call(lambda session: session.call_tool(operation, arguments))

    assert result.isError
    assert control_plane.current().version == 1
    assert control_plane.current().mission == "Original"


@pytest.mark.parametrize("initial_version", [0, 1])
@pytest.mark.parametrize("conditional", [False, True])
def test_given_null_or_matching_version_when_apply_direction_runs_over_mcp_then_write_succeeds(
    mcp_runner, initial_version, conditional
):
    runner, control_plane = mcp_runner
    if initial_version:
        control_plane.apply_direction(mission="Original", change_note="init")

    result = runner.call(
        lambda session: session.call_tool(
            "apply_direction",
            {
                "expected_version": initial_version if conditional else None,
                "mission": "Updated",
                "change_note": "update",
            },
        )
    )

    assert not result.isError
    assert control_plane.current().version == initial_version + 1
    assert control_plane.current().mission == "Updated"


@pytest.mark.asyncio
async def test_given_a_subscribed_session_when_the_version_bumps_then_it_is_notified(cp):
    server = mcp_server.build_server(cp)

    received = []

    class FakeSession:
        async def send_resource_updated(self, uri):
            received.append(str(uri))

    server._kyno_subscribers.add(FakeSession())
    mcp_handlers.handle_apply_direction(
        cp, mission="M1", principles=["p1"], change_note="init", created_by=None
    )
    await asyncio.gather(*server._kyno_pending)
    assert received == [RESOURCE_URI]


@pytest.mark.asyncio
async def test_given_an_mcp_subscriber_raises_when_notifying_then_another_receives_the_update(cp):
    server = mcp_server.build_server(cp)
    received = []

    class BrokenSession:
        async def send_resource_updated(self, _uri):
            raise RuntimeError("session closed")

    class HealthySession:
        async def send_resource_updated(self, uri):
            received.append(str(uri))

    broken = BrokenSession()
    healthy = HealthySession()
    server._kyno_subscribers.update((broken, healthy))

    result = mcp_handlers.handle_apply_direction(
        cp, mission="M1", principles=["p1"], change_note="init", created_by=None
    )
    await asyncio.gather(*server._kyno_pending)

    assert result["version"] == 1
    assert received == [RESOURCE_URI]
    assert server._kyno_subscribers == {healthy}


def test_given_no_running_loop_when_notifying_then_it_is_a_noop(cp):
    # No running event loop means no async subscribers are reachable;
    # the notify hook must not raise anyway.
    server = mcp_server.build_server(cp)
    server._kyno_subscribers.add(object())
    mcp_handlers.handle_apply_direction(
        cp, mission="M1", principles=["p1"], change_note="init", created_by=None
    )


@pytest.mark.asyncio
async def test_given_missing_required_args_when_dispatching_a_tool_call_then_the_reject_is_clean(
    cp,
):
    # Guards against a raw KeyError leaking out of dispatch instead of a clean error result.
    import mcp.types as types

    server = mcp_server.build_server(cp)
    handler = server.request_handlers[types.CallToolRequest]

    for tool_name in ("get_changes_since", "apply_direction"):
        req = types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(name=tool_name, arguments={}),
        )
        result = await handler(req)
        assert result.root.isError is True


@pytest.mark.parametrize(
    "operation,arguments,field,expected",
    [
        ("get_constitution", {}, "mission", "Support mission"),
        ("get_changes_since", {"last_seen_version": 0}, "mission", "Support mission"),
        ("get_mission", {}, "mission", "Support mission"),
        ("get_declaration", {}, "declaration", "Support declaration"),
        ("get_principle", {"title": "Be clear"}, "description", "Explain support options"),
        ("get_principles", {}, "principles", [{"title": "Be clear"}]),
        (
            "get_principles",
            {"detail": "full"},
            "principles",
            [{"title": "Be clear", "description": "Explain support options"}],
        ),
    ],
    ids=[
        "get_constitution",
        "get_changes_since",
        "get_mission",
        "get_declaration",
        "get_principle",
        "get_principles_titles",
        "get_principles_full",
    ],
)
def test_given_distinct_constitutions_when_call_tool_receives_key_then_selected_content_returns(
    mcp_runner, operation, arguments, field, expected
):
    runner, control_plane = mcp_runner
    control_plane.apply_direction(
        mission="Default mission",
        declaration="Default declaration",
        principles=[{"title": "Default principle", "description": "Explain default options"}],
        change_note="initial",
    )
    control_plane.apply_direction(
        constitution_key="support",
        mission="Support mission",
        declaration="Support declaration",
        principles=[{"title": "Be clear", "description": "Explain support options"}],
        change_note="initial",
    )

    result = runner.call(
        lambda session: session.call_tool(operation, {**arguments, "constitution_key": "support"})
    )

    assert not result.isError
    assert json.loads(result.content[0].text)[field] == expected


def test_given_distinct_histories_when_export_versions_receives_key_then_selected_history_returns(
    mcp_runner,
):
    runner, control_plane = mcp_runner
    control_plane.apply_direction(mission="Default mission", change_note="initial")
    control_plane.apply_direction(
        constitution_key="support", mission="Initial support mission", change_note="initial"
    )
    control_plane.apply_direction(
        constitution_key="support", mission="Updated support mission", change_note="update"
    )

    result = runner.call(
        lambda session: session.call_tool("export_versions", {"constitution_key": "support"})
    )

    assert not result.isError
    versions = json.loads(result.content[0].text)
    assert len(versions) == 2
    assert versions[0]["mission"] == "Initial support mission"
    assert versions[1]["mission"] == "Updated support mission"
